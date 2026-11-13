"""User-facing offline and disabled commands must not need a DB or LLM API key."""

from __future__ import annotations

import json

import pytest

from derai_scheduler import cli


@pytest.fixture
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SOCIAL_COLLECTION_ENABLED", "true")
    monkeypatch.setenv("WORKER_INTERVAL", "60")
    monkeypatch.setenv("CONNECTOR_ARTICLE_MAX_PAGES", "1")
    return ["--env-file", str(tmp_path / "does-not-exist.env")]


def forbid_database(*args, **kwargs):
    raise AssertionError("This command must not create a database engine")


def test_disabled_tick_succeeds_without_database_url(
    isolated_environment, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("SOCIAL_COLLECTION_ENABLED", "off")
    monkeypatch.setattr(cli, "create_database_engine", forbid_database)
    assert cli.main([*isolated_environment, "tick"]) == 0
    assert json.loads(capsys.readouterr().out) == {"worker": "collection-scheduler", "processed": 0}


def test_offline_preview_matches_four_row_prd_fixture(
    isolated_environment, monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setattr(cli, "create_database_engine", forbid_database)
    path = tmp_path / "topics.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "11111111-1111-4111-8111-111111111111",
                    "tenant_id": "22222222-2222-4222-8222-222222222222",
                    "workspace_id": "33333333-3333-4333-8333-333333333333",
                    "kind": "topic",
                    "status": "ready",
                    "data": json.dumps({"keywords": [" TNI ", "Indonesia", "tni", ""]}),
                }
            ]
        ),
        encoding="utf-8",
    )
    assert (
        cli.main(
            [
                *isolated_environment,
                "preview",
                "--topics",
                str(path),
                "--at",
                "2026-11-13T11:37:20+07:00",
            ]
        )
        == 0
    )
    record = json.loads(capsys.readouterr().out)
    assert record["worker"] == "collection-scheduler"
    assert record["mode"] == "preview"
    assert record["processed"] == len(record["jobs"]) == 4
    payloads = [json.loads(row["data"]) for row in record["jobs"]]
    assert {payload["query"] for payload in payloads} == {"TNI", "Indonesia"}
    assert {payload["scheduled_for"] for payload in payloads} == {"2026-11-13T04:00:00+00:00"}
    assert {row["name"] for row in record["jobs"]} == {"social-media", "online-news"}
    assert all(row["status"] == "queued" and row["kind"] == "job" for row in record["jobs"])


def test_enabled_tick_requires_database_url_and_reports_safe_failure(
    isolated_environment, capsys
) -> None:
    assert cli.main([*isolated_environment, "tick"]) == 1
    record = json.loads(capsys.readouterr().out)
    assert record["worker"] == "collection-scheduler"
    assert record["error"] == "ValueError"
    assert "processed" not in record


def test_bad_fixture_does_not_leak_its_contents(isolated_environment, tmp_path, capsys) -> None:
    path = tmp_path / "bad-topics.json"
    private_content = "private-topic-body-or-token"
    path.write_text(private_content, encoding="utf-8")
    assert cli.main([*isolated_environment, "preview", "--topics", str(path)]) == 1
    captured = capsys.readouterr()
    assert private_content not in captured.out + captured.err
    assert json.loads(captured.out)["error"] == "JSONDecodeError"


def test_invalid_env_encoding_reports_sanitized_failure(monkeypatch, tmp_path, capsys) -> None:
    path = tmp_path / "invalid.env"
    private_content = "private-environment-password"
    path.write_bytes(b"\xffDATABASE_URL=" + private_content.encode())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert cli.main(["--env-file", str(path), "tick"]) == 1
    captured = capsys.readouterr()
    assert private_content not in captured.out + captured.err
    record = json.loads(captured.out)
    assert record["worker"] == "collection-scheduler"
    assert record["error"] == "UnicodeDecodeError"
