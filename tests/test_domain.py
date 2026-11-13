"""Payload and normalization contracts copied from the mentor PRD, not the implementation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from derai_scheduler.domain import Topic, build_jobs, normalize_tick

TOPIC_ID = "11111111-1111-4111-8111-111111111111"
TENANT_ID = "22222222-2222-4222-8222-222222222222"
WORKSPACE_ID = "33333333-3333-4333-8333-333333333333"
TICK = datetime.fromisoformat("2026-11-13T11:37:20+07:00")
WRITE_TIME = datetime.fromisoformat("2026-11-13T05:12:34.123456+00:00")
HOUR = "2026-11-13T04:00:00+00:00"


def topic_with(keywords: list[object]) -> Topic:
    return Topic(TOPIC_ID, TENANT_ID, WORKSPACE_ID, json.dumps({"keywords": keywords}))


def jobs_for(keywords: list[object], **kwargs: object) -> list:
    return list(build_jobs(topic_with(keywords), TICK, clock=lambda: WRITE_TIME, **kwargs))


def payloads_by_name(jobs: list) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for job in jobs:
        assert isinstance(job.data, str), "records.data must be serialized JSON text"
        payload = json.loads(job.data)
        assert isinstance(payload, dict), "Do not double-encode records.data"
        result.setdefault(job.name, []).append(payload)
    return result


def test_prd_example_produces_four_jobs_with_exact_payloads() -> None:
    jobs = jobs_for([" TNI ", "Indonesia", "tni", ""])
    assert len(jobs) == 4
    by_name = payloads_by_name(jobs)
    assert [p["query"] for p in by_name["social-media"]] == ["TNI", "Indonesia"]
    assert [p["query"] for p in by_name["online-news"]] == ["TNI", "Indonesia"]

    assert by_name["social-media"][0] == {
        "topic_id": TOPIC_ID,
        "connector": "social-media",
        "query": "TNI",
        "search_type": "keyword",
        "fetch_mode": "page",
        "limit_per_platform": 10,
        "options": {},
        "scheduled_for": HOUR,
        "period_start": "2026-11-13T03:00:00+00:00",
        "period_end": HOUR,
    }
    assert by_name["online-news"][0] == {
        "topic_id": TOPIC_ID,
        "connector": "social-media",
        "query": "TNI",
        "platforms": ["online_news"],
        "search_type": "keyword",
        "fetch_mode": "page",
        "limit_per_platform": 10,
        "options": {"online_news": {"max_pages": "1"}},
        "scheduled_for": HOUR,
    }


def test_prd_hash_examples_are_exact() -> None:
    tni = jobs_for(["TNI"])
    assert {job.idempotency_key for job in tni} == {
        f"collection:{TOPIC_ID}:b08f256307ea4e66:{HOUR}",
        f"collection:{TOPIC_ID}:b08f256307ea4e66:online_news:{HOUR}",
    }
    street = jobs_for([" Straße ", "STRASSE"])
    assert len(street) == 2
    assert {json.loads(job.data)["query"] for job in street} == {"Straße"}
    assert {job.idempotency_key for job in street} == {
        f"collection:{TOPIC_ID}:16d96952087774fe:{HOUR}",
        f"collection:{TOPIC_ID}:16d96952087774fe:online_news:{HOUR}",
    }


@pytest.mark.parametrize(
    "tick",
    [
        datetime.fromisoformat("2026-11-13T11:37:20+07:00"),
        datetime.fromisoformat("2026-11-13T04:37:20Z"),
        datetime(2026, 11, 13, 4, 37, 20),
        datetime(2026, 11, 12, 23, 37, 20, tzinfo=timezone(-timedelta(hours=5))),
    ],
)
def test_timezone_and_naive_utc_have_identical_schedule_and_keys(tick: datetime) -> None:
    jobs = list(build_jobs(topic_with(["TNI"]), tick))
    assert normalize_tick(tick) == datetime(2026, 11, 13, 4, tzinfo=UTC)
    assert {json.loads(job.data)["scheduled_for"] for job in jobs} == {HOUR}
    assert all(job.idempotency_key.endswith(HOUR) for job in jobs)


def test_hour_floor_removes_seconds_and_microseconds() -> None:
    assert normalize_tick(datetime(2026, 11, 13, 4, 59, 59, 999999, UTC)) == datetime(
        2026, 11, 13, 4, tzinfo=UTC
    )


def test_python_strip_casefold_and_legacy_string_conversion() -> None:
    jobs = jobs_for(["\u2003 TNI\u00a0", "tni", None, True, False, 42, "42", "\t\r\n"])
    social = payloads_by_name(jobs)["social-media"]
    assert [payload["query"] for payload in social] == ["TNI", "None", "True", "False", "42"]
    assert len(jobs) == 10


@pytest.mark.parametrize("data", ["{}", '{"keywords": []}'])
def test_absent_or_empty_keywords_produce_no_jobs(data: str) -> None:
    topic = Topic(TOPIC_ID, TENANT_ID, WORKSPACE_ID, data)
    assert list(build_jobs(topic, TICK)) == []


@pytest.mark.parametrize("data", ["not json", "[]", "null", '{"keywords": "TNI"}'])
def test_malformed_topic_fails_instead_of_silently_scheduling(data: str) -> None:
    topic = Topic(TOPIC_ID, TENANT_ID, WORKSPACE_ID, data)
    with pytest.raises((TypeError, ValueError)):
        list(build_jobs(topic, TICK))


def test_news_max_pages_stays_string_and_social_options_stay_empty() -> None:
    by_name = payloads_by_name(jobs_for(["TNI"], article_max_pages="3"))
    assert by_name["online-news"][0]["options"] == {"online_news": {"max_pages": "3"}}
    assert by_name["social-media"][0]["options"] == {}


def test_database_envelope_uses_canonical_uuid_v4_and_actual_write_clock() -> None:
    jobs = jobs_for(["TNI"])
    assert len({job.id for job in jobs}) == 2
    for job in jobs:
        assert str(UUID(job.id)) == job.id
        assert UUID(job.id).version == 4
        assert job.tenant_id == TENANT_ID
        assert job.workspace_id == WORKSPACE_ID
        assert job.parent_id == TOPIC_ID
        assert job.kind == "job"
        assert job.status == "queued"
        assert job.created_at.endswith("+00:00")
        assert datetime.fromisoformat(job.created_at) == WRITE_TIME
        assert len(job.idempotency_key) <= 200


def test_hour_rollover_uses_only_current_hour_without_backfill() -> None:
    topic = topic_with(["TNI"])
    old_jobs = list(build_jobs(topic, TICK))
    later_jobs = list(build_jobs(topic, TICK + timedelta(hours=5)))
    assert len(later_jobs) == 2
    assert {json.loads(job.data)["scheduled_for"] for job in later_jobs} == {
        "2026-11-13T09:00:00+00:00"
    }
    assert {j.idempotency_key for j in old_jobs}.isdisjoint(j.idempotency_key for j in later_jobs)


def test_scope_and_topic_identity_are_copied_per_topic() -> None:
    topic = Topic("another-topic", "another-tenant", "another-workspace", '{"keywords":["TNI"]}')
    jobs = list(build_jobs(topic, TICK))
    assert len(jobs) == 2
    for job in jobs:
        assert (job.parent_id, job.tenant_id, job.workspace_id) == (
            "another-topic",
            "another-tenant",
            "another-workspace",
        )
        assert json.loads(job.data)["topic_id"] == "another-topic"
        assert job.idempotency_key.startswith("collection:another-topic:")
