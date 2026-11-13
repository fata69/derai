"""Call the original DERAI worker from its image on disposable fixture databases.

Run from the legacy image's application directory. Connect the container only
to the fixture PostgreSQL network namespace; do not load production settings.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

DEFAULT_TICK = datetime.fromisoformat("2026-11-13T11:37:20+07:00")
FIXTURE_DATABASES = {
    "legacy-tick": "derai_reference_old",
    "verify-ingestion": "derai_reference_new",
}


class VerificationError(RuntimeError):
    """A fixture failure whose message contains no record contents or secrets."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def configure_fixture(command: str):
    expected = FIXTURE_DATABASES[command]
    dsn = os.environ.get("DATABASE_URL", "")
    try:
        url = make_url(dsn)
    except Exception:
        raise VerificationError("Set DATABASE_URL to the isolated fixture PostgreSQL URL") from None
    require(
        url.get_backend_name() == "postgresql"
        and url.host == "127.0.0.1"
        and url.username == "derai_worker"
        and url.database == expected
        and not url.query,
        f"Expected loopback PostgreSQL database {expected}, role derai_worker, no query overrides",
    )
    # libpq can otherwise substitute a host address or service definition even
    # when the explicit URL has been validated. Keep only the fixture password.
    for key in tuple(os.environ):
        if key.startswith("PG") and key != "PGPASSWORD":
            os.environ.pop(key)

    # A read-only mount of this script can live outside the legacy application's
    # directory. The legacy image's working directory owns the app package.
    sys.path.insert(0, str(Path.cwd()))
    from app import workers

    workers.db.configure(dsn)
    with workers.db.Session() as session:
        identity = session.execute(
            text("SELECT current_database(), current_user, host(inet_server_addr())")
        ).one()
        require(
            tuple(identity) == (expected, "derai_worker", "127.0.0.1"),
            "Database session identity did not match the fixture",
        )
    return workers


def utc_hour(at: datetime) -> datetime:
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def verify_ingestion(workers, tick: datetime) -> dict:
    end = utc_hour(tick)
    start = end - timedelta(hours=1)
    kinds = {"social-media", "online-news"}
    record = workers.Record
    with workers.db.Session() as session:
        rows = session.scalars(select(record)).all()
        topics = [row for row in rows if row.kind == "topic"]
        jobs = [row for row in rows if row.kind == "job"]
        require(
            len(rows) == 3 and len(topics) == 1 and len(jobs) == 2,
            "Ingestion requires a fresh fixture with exactly one topic and two jobs",
        )
        topic = topics[0]
        require({row.name for row in jobs} == kinds, "Expected both scheduler job kinds")
        for row in jobs:
            payload = json.loads(row.data)
            require(
                row.status == "queued"
                and row.parent_id == topic.id
                and payload.get("topic_id") == topic.id
                and payload.get("query") == "TNI"
                and payload.get("scheduled_for") == end.isoformat(),
                "Unexpected queued fixture job",
            )
            if row.name == "social-media":
                require(
                    "platforms" not in payload
                    and payload.get("period_start") == start.isoformat()
                    and payload.get("period_end") == end.isoformat(),
                    "Social job does not carry the expected period/default platform contract",
                )
            else:
                require(
                    "period_start" not in payload and "period_end" not in payload,
                    "News job must not carry a collection period",
                )
        job_ids = {row.id for row in jobs}

    calls = []
    writes = []

    def item(source_id: str, platform: str, at: datetime) -> SimpleNamespace:
        timestamp = at.isoformat()
        return SimpleNamespace(
            source_id=source_id,
            platform=platform,
            checkpoint=source_id,
            payload=json.dumps(
                {
                    "platform": platform,
                    "item": {"id": source_id, "created_at": timestamp, "text": source_id},
                }
            ).encode(),
        )

    class FixtureConnector:
        def __init__(self, **kwargs):
            self.platforms = kwargs["platforms"]
            # Record only inputs relevant to compatibility, never credentials.
            calls.append({k: kwargs[k] for k in ("query", "platforms", "options")})

        def validate_configuration(self) -> bool:
            return True

        def health_check(self) -> bool:
            return True

        def authenticate(self) -> None:
            pass

        def collect(self, checkpoint):
            if self.platforms == ["online_news"]:
                return [item("news_outside_social_hour", "online_news", end + timedelta(hours=2))]
            return [
                item("social_before", "x", start - timedelta(seconds=1)),
                item("social_at_start", "x", start),
                item("social_inside", "youtube", start + timedelta(minutes=30)),
                item("social_at_end", "x", end),
            ]

    class FixtureObjectStore:
        bucket = "reference-parity-fixture"

        def put(self, key: str, payload: bytes) -> None:
            writes.append(json.loads(payload)["item"]["id"])

    with (
        patch.dict(
            os.environ,
            {
                "CONNECTOR_PLATFORMS": "x,youtube",
                "CONNECTOR_BASE_URL": "http://127.0.0.1:1",
                "CONNECTOR_API_KEY": "fixture-only",
                "CONNECTOR_ARTICLE_TIMEOUT_SECONDS": "10",
                "CONNECTOR_TIMEOUT_SECONDS": "10",
                "SOCIAL_FANOUT_ROUTES": "",
                "SOCIAL_FANOUT_TARGETS": "",
            },
        ),
        patch.object(workers, "UnifiedSocialConnector", FixtureConnector),
        patch.object(workers, "ObjectStore", FixtureObjectStore),
    ):
        processed = workers.ingestion_once()

    require(processed == 2, "Original ingestion worker did not process both jobs")
    require(len(calls) == 2, "Expected exactly two connector constructions")
    require(
        {
            "query": "TNI",
            "platforms": ["x", "youtube"],
            "options": {"x": {"start_time": start.isoformat(), "end_time": end.isoformat()}},
        }
        in calls,
        "Original worker did not apply social platforms and the X period",
    )
    require(
        {
            "query": "TNI",
            "platforms": ["online_news"],
            "options": {"online_news": {"max_pages": "3"}},
        }
        in calls,
        "Original worker did not select online news with max_pages as a string",
    )
    accepted = {"social_at_start", "social_inside", "news_outside_social_hour"}
    require(
        set(writes) == accepted and len(writes) == 3,
        "Storage writes do not match the social half-open period and unbounded news",
    )
    with workers.db.Session() as session:
        jobs = session.scalars(select(record).where(record.kind == "job")).all()
        require(
            len(jobs) == 2
            and {row.id for row in jobs} == job_ids
            and all(row.status == "ready" for row in jobs),
            "Both original queued job rows must persist as ready",
        )
        skipped = {row.name: json.loads(row.data).get("skipped_outside_period") for row in jobs}
        require(skipped == {"social-media": 2, "online-news": 0}, "Incorrect period skip counts")
        raw = session.scalars(select(record).where(record.kind == "raw_object")).all()
        outbox = session.scalars(select(record).where(record.kind == "outbox")).all()
        require(
            len(raw) == 3 and {row.name for row in raw} == accepted,
            "Expected three accepted raw fixture records",
        )
        require(
            len(outbox) == 3 and all(row.status == "queued" for row in outbox),
            "Expected three durable outbox records without contacting a broker",
        )
    return {
        "processed": processed,
        "ready": len(jobs),
        "raw": len(raw),
        "outbox": len(outbox),
        "social_skipped_outside_period": skipped["social-media"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in FIXTURE_DATABASES:
        child = commands.add_parser(command)
        child.add_argument("--at", type=datetime.fromisoformat, default=DEFAULT_TICK)
    args = parser.parse_args()
    try:
        workers = configure_fixture(args.command)
        if args.command == "legacy-tick":
            result = {"processed": workers.collection_scheduler_once(now=args.at)}
        else:
            result = verify_ingestion(workers, args.at)
    except VerificationError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
