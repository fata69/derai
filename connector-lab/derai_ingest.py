"""Connector delivery through the DERAI normalized ingestion API."""
from __future__ import annotations

import ipaddress
import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID


class IngestError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (not parsed.hostname or parsed.username or parsed.password
                or parsed.scheme not in {"http", "https"} or port == 0
                or any(ord(c) < 33 for c in value) or "\\" in value):
            raise ValueError()
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise IngestError("URL tidak valid") from None


def _api_url(value):
    parsed = _url(value)
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise IngestError("DERAI_API_URL harus base URL tanpa path atau query")
    if parsed.scheme == "http" and parsed.hostname not in {"api", "localhost"}:
        try:
            host = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            raise IngestError("Pakai HTTPS untuk API DERAI di luar jaringan privat") from None
        if not (host.is_loopback or host in ipaddress.ip_network("10.0.0.0/8")
                or host in ipaddress.ip_network("172.16.0.0/12")
                or host in ipaddress.ip_network("192.168.0.0/16")):
            raise IngestError("Pakai HTTPS untuk API DERAI di luar jaringan privat")
    return value.rstrip("/")


def _uuid4(value):
    try:
        ident = UUID(value)
        if ident.version != 4:
            raise ValueError()
        return str(ident)
    except (ValueError, TypeError, AttributeError):
        raise IngestError("Identitas DERAI harus UUID4") from None


def request(url, *, token, body=None):
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode() if body is not None else None
    if data is not None and len(data) > 2_000_000:
        raise IngestError("Payload melebihi batas API DERAI")
    req = Request(url, data=data, headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "application/json"})
    try:
        with build_opener(NoRedirect(), ProxyHandler({})).open(req, timeout=30) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise IngestError("Respons API DERAI terlalu besar")
            return response.status, json.loads(raw)
    except HTTPError as exc:
        step = "ingest" if body is not None else "cek topik"
        raise IngestError(f"DERAI {step}: HTTP {exc.code}") from None
    except (URLError, OSError, ValueError):
        raise IngestError("API DERAI tidak tersedia, timeout, atau merespons bukan JSON") from None


def article_payload(value):
    """Map the lab format or retain the engine's exact ArticleResponse."""
    if not isinstance(value, dict):
        raise IngestError("Hasil artikel bukan objek")
    if "status" in value:
        if value["status"] != "success":
            raise IngestError("Ekstraksi artikel tidak sukses")
        payload = value
    else:
        payload = {"canonical_url": value.get("canonical_url"), "title": value.get("headline"),
                   "content": value.get("text"), "published_at": value.get("published_at")}
    for name in ("canonical_url", "title", "content"):
        if not isinstance(payload.get(name), str) or not payload[name].strip():
            raise IngestError(f"Field artikel {name} wajib diisi")
    _url(payload["canonical_url"])
    return payload


def persist_to_derai(settings, *, topic_id, tenant_id, workspace_id, platform,
                    content, idempotency_key, observed_at=None, transport=request):
    base = _api_url((settings.get("DERAI_API_URL") or "http://api:8000").strip())
    token = (settings.get("DERAI_API_TOKEN") or "").strip()
    if not token or any(not 33 <= ord(c) <= 126 for c in token):
        raise IngestError("DERAI_API_TOKEN belum diisi atau tidak valid")
    topic, tenant, workspace = map(_uuid4, (topic_id, tenant_id, workspace_id))
    if (not idempotency_key or len(idempotency_key) > 300
            or any(not 33 <= ord(c) <= 126 for c in idempotency_key)):
        raise IngestError("Idempotency key tidak valid")
    if platform == "x":
        post_id = content.get("id")
        if not isinstance(post_id, str) or not post_id.isascii() or not post_id.isdecimal():
            raise IngestError("ID posting X harus string angka")
        if not isinstance(content.get("text"), str) or not content["text"].strip():
            raise IngestError("Teks posting X kosong")
        payload = {"data": [content]}
    elif platform == "online_news":
        payload = article_payload(content)
    else:
        raise IngestError("Platform belum didukung")

    status, info = transport(base + "/api/v1/topics/" + topic, token=token)
    if (status != 200 or not isinstance(info, dict) or info.get("status") in (None, "deleting")
            or tuple(info.get(k) for k in ("id", "tenant_id", "workspace_id")) != (topic, tenant, workspace)):
        raise IngestError("Topik DERAI tidak aktif atau scope tidak cocok")
    if observed_at is None:
        observed_at = payload.get("fetched_at") if platform == "online_news" else None
    try:
        stamp = datetime.fromisoformat(observed_at) if observed_at else datetime.now(timezone.utc)
        if stamp.tzinfo is None:
            raise ValueError()
        stamp = stamp.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        raise IngestError("observed_at harus bertanggal ISO 8601 dengan zona waktu") from None
    status, result = transport(base + "/api/v1/ingestion/normalized", token=token, body={
        "topic_id": topic, "platform": platform, "observed_at": stamp, "payload": payload,
    })
    if not isinstance(result, dict) or result.get("topic_id") != topic:
        raise IngestError("DERAI tidak mengonfirmasi topik tujuan")
    counts = result.get("created"), result.get("existing")
    ids = result.get("raw_object_ids")
    if not isinstance(ids, list) or len(ids) != 1 or any(type(i) is not int for i in counts):
        raise IngestError("DERAI tidak mengonfirmasi tepat satu item")
    _uuid4(ids[0])
    if (status, counts) == (201, (1, 0)):
        delivery_status = "created"
    elif (status, counts) == (200, (0, 1)):
        delivery_status = "existing"
    else:
        raise IngestError("DERAI belum mengonfirmasi bahwa item tersimpan")
    return {"status": delivery_status, "idempotency_key": idempotency_key}
