"""Run inside a network-isolated copy of the current DERAI API image.

Uses a temporary SQLite DB and memory object store. No production environment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
shared = ROOT.parent / "connector-lab"
sys.path.insert(0, str(shared if shared.is_dir() else ROOT / "connector-lab-candidate"))
from derai_ingest import IngestError, persist_to_derai

TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
WORKSPACE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
article = json.loads((ROOT / "artifacts" / "example-article.json").read_text(encoding="utf-8"))
post = json.loads((ROOT / "artifacts" / "example-x.json").read_text(encoding="utf-8"))


def call(path, body, headers=None):
    request = Request("http://127.0.0.1:18739" + path, data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json", **(headers or {})})
    with urlopen(request, timeout=20) as response:
        return response.status, json.load(response)


def main():
    with tempfile.TemporaryDirectory() as directory:
        # Set all config before importing the backend application.
        os.environ.update({
            "DATABASE_URL": "sqlite:///" + directory + "/backend.db",
            "JWT_SECRET": "isolated-test-jwt-key-at-least-thirty-two-characters",
            "DEV_SEED_ENABLED": "true", "DEV_ADMIN_EMAIL": "admin@example.test",
            "DEV_ADMIN_PASSWORD": "isolated backend test password",
            "DEV_TENANT_ID": TENANT, "DEV_WORKSPACE_ID": WORKSPACE,
            "OBJECT_STORE_MODE": "memory",
        })
        import uvicorn
        from sqlalchemy import select
        from app.main import app
        from app.db import db, Record
        from app.storage import ObjectStore

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=18739,
                                              log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise AssertionError("Isolated backend failed to start")
            time.sleep(0.05)
        try:
            _, login = call("/api/v1/auth/login", {"email": "admin@example.test",
                                                   "password": "isolated backend test password"})
            _, topic = call("/api/v1/topics", {"name": "Article HTTP ingestion fixture", "keywords": []},
                            {"Authorization": "Bearer " + login["access_token"]})
            settings = {"DERAI_API_URL": "http://127.0.0.1:18739", "DERAI_API_TOKEN": login["access_token"]}
            scope = dict(topic_id=topic["id"], tenant_id=TENANT, workspace_id=WORKSPACE,
                         idempotency_key="fixture-1")
            for platform, content in (("online_news", article), ("x", post)):
                first = persist_to_derai(settings, **scope, platform=platform, content=content)
                assert first == {"status": "created", "idempotency_key": "fixture-1"}, first
                repeat = persist_to_derai(settings, **scope, platform=platform, content=content)
                assert repeat == {"status": "existing", "idempotency_key": "fixture-1"}, repeat

            with db.Session() as session:
                raw = list(session.scalars(select(Record).where(Record.kind == "raw_object")))
                canonical = list(session.scalars(select(Record).where(Record.kind == "canonical_content")))
                outbox = list(session.scalars(select(Record).where(Record.kind == "outbox", Record.name == "content.raw.collected.v1")))
                assert len(raw) == len(canonical) == len(outbox) == 2
                evidence = {}
                for row in raw:
                    details = json.loads(row.data)
                    evidence[details["platform"]] = json.loads(ObjectStore().get(details["object_key"]))
                    assert row.tenant_id == TENANT and row.workspace_id == WORKSPACE
                assert evidence == {"online_news": article, "x": post}, evidence.keys()
                assert {json.loads(event.data)["payload"]["raw_object_id"] for event in outbox} == {row.id for row in raw}
                ids = {json.loads(row.data)["platform"]: row.name for row in raw}
                assert ids == {"online_news": article["content_hash"], "x": post["id"]}

            # Backend must refuse a topic absent from the token's scope.
            try:
                persist_to_derai(settings, **{**scope, "topic_id": str(uuid4())}, platform="x", content=post)
            except IngestError as exc:
                assert "HTTP 404" in str(exc)
            else:
                raise AssertionError("Backend accepted a topic outside scope")
            try:
                persist_to_derai(settings, **{**scope, "workspace_id": str(uuid4())}, platform="x", content=post)
            except IngestError as exc:
                assert "scope tidak cocok" in str(exc)
            else:
                raise AssertionError("Mismatched scope was not caught before POST")
            report = {"result": "passed", "backend": "current DERAI API image",
                      "endpoint": "/api/v1/ingestion/normalized", "platforms": ["x", "online_news"],
                      "isolation": "network none, temporary SQLite DB, memory object store",
                      "raw": 2, "canonical": 2, "outbox": 2,
                      "repeat": "existing for both platforms", "stored_evidence_exact": True,
                      "invalid_topic": "HTTP 404", "scope_mismatch": "blocked before POST",
                      "production_data_written": False}
            (ROOT / "artifacts" / "backend-verification.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2))
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    main()
