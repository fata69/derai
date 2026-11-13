import json
import sys

import connector_lab
import httpx
import pytest
from connector_lab import Article, LabError, Page, Settings, extract_article, public_url


def test_selects_provider_and_calls_compatible_endpoint(tmp_path, monkeypatch):
    for key in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=openrouter\nLLM_MODEL=openrouter/free\nLLM_API_KEY=example-key\n"
        "LLM_BASE_URL=https://unused.invalid/v1\n",
        encoding="utf-8",
    )
    settings = Settings.load(env_file)
    assert "example-key" not in repr(settings)
    page = Page("# Judul contoh\n\nIsi contoh.", "https://example.org/artikel")

    def provider(request):
        assert request.url == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer example-key"
        payload = json.loads(request.content)
        assert payload["model"] == "openrouter/free"
        assert payload["messages"][1]["content"] == page.markdown
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "```json\n"
                            + json.dumps(
                                {
                                    "headline": "Judul contoh",
                                    "text": "Isi contoh.",
                                    "canonical_url": "https://untrusted.invalid",
                                    "published_at": "2026-11-13T04:00:00Z",
                                }
                            )
                            + "\n```"
                        }
                    },
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        assert extract_article(client, settings, page) == Article(
            "Judul contoh", "Isi contoh.", page.canonical_url, "2026-11-13T04:00:00Z"
        )


@pytest.mark.parametrize(
    ("provider", "model", "base_url", "key", "endpoint"),
    [
        (
            "gemini",
            "gemini-3.5-flash-lite",
            "",
            "test-gemini-key",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        ),
        (
            "compatible",
            "fixture-local-model",
            "http://127.0.0.1:8000/v1/",
            "",
            "http://127.0.0.1:8000/v1/chat/completions",
        ),
    ],
)
def test_cli_article_json_offline(
    tmp_path, monkeypatch, capsys, provider, model, base_url, key, endpoint
):
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / "provider.env"
    env_file.write_text(
        f"LLM_PROVIDER={provider}\nLLM_MODEL={model}\nLLM_API_KEY={key}\nLLM_BASE_URL={base_url}\n",
        encoding="utf-8",
    )
    url = "https://example.org/artikel?source=fixture"
    page = Page(
        "# Café di Jakarta\n\nArtikel contoh dari halaman publik.", "https://example.org/artikel"
    )
    model_article = {"headline": "Café di Jakarta", "text": "Artikel contoh dari halaman publik."}

    async def crawl_fixture(article_url, *, browser_channel):
        assert article_url == url
        assert browser_channel == "chrome"
        print("crawler diagnostic")
        return page

    def provider_fixture(request):
        assert request.method == "POST"
        assert str(request.url) == endpoint
        assert request.headers.get("Authorization") == (f"Bearer {key}" if key else None)
        payload = json.loads(request.content)
        assert payload["model"] == model
        assert payload["messages"][-1] == {"role": "user", "content": page.markdown}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(model_article)}}]}
        )

    client_type = httpx.Client

    def mock_client(**kwargs):
        return client_type(transport=httpx.MockTransport(provider_fixture), **kwargs)

    monkeypatch.setattr(connector_lab, "crawl_article", crawl_fixture)
    monkeypatch.setattr(connector_lab.httpx, "Client", mock_client)
    monkeypatch.setattr(
        sys,
        "argv",
        ["connector_lab.py", url, "--env-file", str(env_file), "--browser-channel", "chrome"],
    )

    assert connector_lab.main() == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        **model_article,
        "canonical_url": page.canonical_url,
        "published_at": None,
    }
    assert output.err == "crawler diagnostic\n"


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (429, {"error": "provider-debug-secret"}, "HTTP 429"),
        (200, {"choices": [{"message": {"content": "bad JSON"}}]}, "JSON artikel"),
        (200, {"choices": []}, "format Chat Completions"),
    ],
)
def test_provider_errors_are_actionable_and_hide_response(status, body, message):
    settings = Settings("compatible", "http://127.0.0.1:8000/v1", "fixture", "test-token")
    transport = httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(LabError, match=message) as error,
    ):
        extract_article(client, settings, Page("text", "https://example.org/article"))
    assert "provider-debug-secret" not in str(error.value)
    assert "test-token" not in str(error.value)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://127.0.0.1", "https://user@example.org"]
)
def test_article_url_rejects_local_files_addresses_and_userinfo(url):
    with pytest.raises(LabError, match="URL artikel"):
        public_url(url)


def test_env_read_error_is_safe(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"LLM_API_KEY=secret-value\xff")
    with pytest.raises(LabError, match="UTF-8") as error:
        Settings.load(env_file)
    assert "secret-value" not in str(error.value)
