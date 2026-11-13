"""Local preview, one-shot contract tick, and long-running scheduler entry points."""

from __future__ import annotations

import argparse
import json
import signal
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .config import Settings
from .domain import Topic, as_utc, build_jobs, utc_now
from .runtime import WORKER, FixedDelayRunner, emit, safe_error, tick_and_log
from .service import SchedulerService
from .store import PostgreSQLStore, create_database_engine


def parse_time(value: str) -> datetime:
    try:
        return as_utc(datetime.fromisoformat(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Use an ISO 8601 datetime, for example 2026-11-13T11:37:20+07:00"
        ) from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="DERAI PostgreSQL collection scheduler")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument(
        "--env-file", default=".env", help="Optional dotenv file; existing env wins"
    )
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="Run immediately, then wait WORKER_INTERVAL after each tick")
    once = commands.add_parser("tick", help="Commit one PostgreSQL tick")
    once.add_argument("--at", type=parse_time, help="Fixed tick time for contract checks")
    preview = commands.add_parser(
        "preview", help="Generate records offline without writing to a DB"
    )
    preview.add_argument("--topics", type=Path, required=True, help="JSON array of topic records")
    preview.add_argument("--at", type=parse_time, help="Fixed tick time for contract checks")
    return result


def preview_jobs(path: Path, settings: Settings, now: datetime | None) -> None:
    tick_time = now if now is not None else utc_now()
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list):
        raise ValueError("Fixture must be a JSON array of topic records")
    jobs = []
    if settings.enabled:
        for row in rows:
            if row.get("kind") != "topic" or row.get("status") in {None, "deleting"}:
                continue
            topic = Topic(**{key: row[key] for key in ("id", "tenant_id", "workspace_id", "data")})
            jobs.extend(
                asdict(job) for job in build_jobs(topic, tick_time, settings.article_max_pages)
            )
    emit({"worker": WORKER, "mode": "preview", "processed": len(jobs), "jobs": jobs})


def request_shutdown(_signum, _frame) -> None:
    # Do not acquire locks in a signal handler. Unwind the scheduler stack first.
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    engine = None
    try:
        load_dotenv(args.env_file, override=False, encoding="utf-8-sig")
        settings = Settings.from_env()
        if args.command == "preview":
            preview_jobs(args.topics, settings, args.at)
            return 0
        if settings.enabled:
            engine = create_database_engine(settings)
            store = PostgreSQLStore(engine)
        else:
            # Disabled mode intentionally needs neither a connection nor a topic query.
            store = None
        service = SchedulerService(store, settings)  # type: ignore[arg-type]
        if args.command == "tick":
            return 0 if tick_and_log(service, args.at) else 1

        runner = FixedDelayRunner(service, settings.worker_interval)
        previous_handlers = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[sig] = signal.signal(sig, request_shutdown)
        try:
            runner.run()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                # A second stop signal must not interrupt an in-flight commit.
                for sig in previous_handlers:
                    signal.signal(sig, signal.SIG_IGN)
                runner.stop()
            finally:
                for sig, handler in previous_handlers.items():
                    signal.signal(sig, handler)
        return 0
    except Exception as exc:
        emit(safe_error(exc))
        return 1
    finally:
        if engine is not None:
            engine.dispose()
