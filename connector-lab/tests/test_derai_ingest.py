import json

import httpx
import pytest

from derai_ingest import IngestError, persist_to_derai
from x_post import PostError, extract_post

TOPIC = "11111111-1111-4111-8111-111111111111"
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
WORKSPACE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SCOPE = {"topic_id": TOPIC, "tenant_id": TENANT, "workspace_id": WORKSPACE,
         "idempotency_key": "cron:key"}
SETTINGS = {"DERAI_API_URL": "http://api:8000", "DERAI_API_TOKEN": "fixture-token"}
POST = {"id": "463440424141459456", "text": "Teks asli", "source_url": "https://x.com/abc/status/463440424141459456"}
ARTICLE = {"status": "success", "canonical_url": "https://example.org/berita", "title": "Judul",
           "content": "Isi", "published_at": None, "fetched_at": "2026-11-17T19:00:00+07:00"}


@pytest.mark.parametrize("platform,content,expected,status,counts", [
    ("x", POST, {"data": [POST]}, 201, (1, 0)),
    ("online_news", ARTICLE, ARTICLE, 200, (0, 1)),
])
def test_normalized_sends_original_item(platform, content, expected, status, counts):
    seen = []

    def api(url, token, body=None):
        assert token == "fixture-token"
        seen.append((url, body))
        if body is None:
            return 200, {"id": TOPIC, "tenant_id": TENANT, "workspace_id": WORKSPACE, "status": "ready"}
        return status, {"topic_id": TOPIC, "created": counts[0], "existing": counts[1], "raw_object_ids": [TOPIC]}

    receipt = persist_to_derai(SETTINGS, **SCOPE, platform=platform, content=content, transport=api)
    assert seen[0] == ("http://api:8000/api/v1/topics/" + TOPIC, None)
    assert seen[1][0] == "http://api:8000/api/v1/ingestion/normalized"
    assert seen[1][1]["payload"] == expected
    assert seen[1][1]["platform"] == platform and seen[1][1]["observed_at"].endswith("+00:00")
    assert receipt == {"status": "created" if status == 201 else "existing", "idempotency_key": "cron:key"}


def test_never_posts_for_wrong_workspace():
    def api(url, token, body=None):
        assert body is None
        return 200, {"id": TOPIC, "tenant_id": TENANT, "workspace_id": TENANT, "status": "ready"}
    with pytest.raises(IngestError, match="scope"):
        persist_to_derai(SETTINGS, **SCOPE, platform="x", content=POST, transport=api)


def test_empty_ack_never_marks_success():
    def api(url, token, body=None):
        if body is None:
            return 200, {"id": TOPIC, "tenant_id": TENANT, "workspace_id": WORKSPACE, "status": "ready"}
        return 200, {"topic_id": TOPIC, "created": 0, "existing": 0, "raw_object_ids": []}
    with pytest.raises(IngestError, match="tepat satu"):
        persist_to_derai(SETTINGS, **SCOPE, platform="x", content=POST, transport=api)


@pytest.mark.parametrize("id_in_embed,valid", [(POST["id"], True), ("123", False)])
def test_x_checks_target_id_and_keeps_text(id_in_embed, valid):
    def api(request):
        assert request.url.host == "publish.x.com"
        assert request.url.params["url"] == POST["source_url"]
        html = (f'<blockquote class="twitter-tweet"><p>Teks &amp;<br>asli</p>'
                f'<a href="https://x.com/abc/status/{id_in_embed}">date</a></blockquote>')
        return httpx.Response(200, json={"url": POST["source_url"], "html": html})
    with httpx.Client(transport=httpx.MockTransport(api)) as client:
        if valid:
            assert extract_post(client, POST["source_url"])["text"] == "Teks &\nasli"
        else:
            with pytest.raises(PostError, match="Identitas"):
                extract_post(client, POST["source_url"])


def test_x_generic_web_url_is_normalized_for_oembed():
    ident = POST["id"]
    def api(request):
        assert request.url.params["url"] == f"https://x.com/i/status/{ident}"
        html = f'<blockquote class="twitter-tweet"><p>Teks asli</p><a href="{POST["source_url"]}">date</a></blockquote>'
        return httpx.Response(200, json={"url": POST["source_url"], "html": html})
    with httpx.Client(transport=httpx.MockTransport(api)) as client:
        assert extract_post(client, f"https://x.com/i/web/status/{ident}") == POST
