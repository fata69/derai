"""Pure PRD contract: normalize a topic into two queued records per unique keyword."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    # The legacy worker interprets naive test times as UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def normalize_tick(value: datetime) -> datetime:
    return as_utc(value).replace(minute=0, second=0, microsecond=0)


def utc_iso(value: datetime, *, seconds: bool = False) -> str:
    return as_utc(value).isoformat(timespec="seconds" if seconds else "microseconds")


@dataclass(frozen=True)
class Topic:
    id: str
    tenant_id: str
    workspace_id: str
    data: str


@dataclass(frozen=True)
class Job:
    id: str
    tenant_id: str
    workspace_id: str
    kind: str
    parent_id: str
    name: str
    data: str
    status: str
    idempotency_key: str
    created_at: str


def unique_keywords(data: str) -> Iterator[tuple[str, str]]:
    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        raise ValueError("Topic data must be a JSON object")
    keywords = parsed.get("keywords", [])
    if not isinstance(keywords, list):
        raise ValueError("Topic keywords must be a JSON array")
    seen: set[str] = set()
    for raw in keywords:
        query = str(raw).strip()
        if not query:
            continue
        normalized = query.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        yield query, normalized


def build_jobs(
    topic: Topic,
    tick_time: datetime,
    article_max_pages: str = "1",
    clock: Callable[[], datetime] = utc_now,
) -> Iterator[Job]:
    hour = normalize_tick(tick_time)
    scheduled_for = utc_iso(hour, seconds=True)
    period_start = utc_iso(hour - timedelta(hours=1), seconds=True)
    for query, normalized in unique_keywords(topic.data):
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        common = {
            "topic_id": topic.id,
            "connector": "social-media",
            "query": query,
            "search_type": "keyword",
            "fetch_mode": "page",
            "limit_per_platform": 10,
            "scheduled_for": scheduled_for,
        }
        social = {
            **common,
            "options": {},
            "period_start": period_start,
            "period_end": scheduled_for,
        }
        news = {
            **common,
            "platforms": ["online_news"],
            "options": {"online_news": {"max_pages": article_max_pages}},
        }
        for name, payload, key in (
            ("social-media", social, f"collection:{topic.id}:{digest}:{scheduled_for}"),
            (
                "online-news",
                news,
                f"collection:{topic.id}:{digest}:online_news:{scheduled_for}",
            ),
        ):
            yield Job(
                id=str(uuid4()),
                tenant_id=topic.tenant_id,
                workspace_id=topic.workspace_id,
                kind="job",
                parent_id=topic.id,
                name=name,
                data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                status="queued",
                idempotency_key=key,
                created_at=utc_iso(clock()),
            )
