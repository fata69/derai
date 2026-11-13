"""APScheduler lifecycle with immediate startup and delay measured after completion."""

from __future__ import annotations

import json
import logging
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TextIO

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.exc import SQLAlchemyError

from .domain import utc_now
from .service import SchedulerService

WORKER = "collection-scheduler"


def safe_error(exc: Exception) -> dict[str, str]:
    # Do not stringify database/JSON exceptions: they may include query parameters,
    # complete topic content, passwords, tokens, or a connection URL.
    if isinstance(exc, json.JSONDecodeError):
        message = "Topic data is not valid JSON; the tick was rolled back."
    elif isinstance(exc, SQLAlchemyError):
        message = (
            "PostgreSQL operation failed; the tick was rolled back. Check connectivity and grants."
        )
    elif isinstance(exc, ValueError):
        message = "Invalid configuration or topic data; no tick changes were committed."
    elif isinstance(exc, OSError):
        message = "A local file or network operation failed."
    else:
        message = "Tick failed; no tick changes were committed."
    return {"worker": WORKER, "error": type(exc).__name__, "message": message}


def emit(record: dict, stream: TextIO | None = None) -> None:
    print(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")),
        file=stream or sys.stdout,
        flush=True,
    )


def tick_and_log(service: SchedulerService, now: datetime | None = None) -> bool:
    try:
        processed = service.tick(now=now)
    except Exception as exc:
        emit(safe_error(exc))
        return False
    emit({"worker": WORKER, "processed": processed})
    return True


class FixedDelayRunner:
    def __init__(
        self,
        service: SchedulerService,
        interval: float,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.service = service
        self.interval = interval
        self.clock = clock
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._sequence = 0
        # Framework logs can contain raw exception data. Our wrapper emits the
        # sanitized, PRD-compatible worker records instead.
        scheduler_logger = logging.getLogger("apscheduler")
        scheduler_logger.addHandler(logging.NullHandler())
        scheduler_logger.propagate = False
        scheduler_logger.setLevel(logging.CRITICAL)
        self.scheduler = BlockingScheduler(
            timezone=UTC,
            executors={"default": ThreadPoolExecutor(max_workers=1)},
            job_defaults={"max_instances": 1, "misfire_grace_time": None},
        )

    def _schedule(self, when: datetime) -> None:
        with self._lock:
            if not self._stopping.is_set():
                # The scheduler removes a fired date job after submitting it.
                # A fast callback must not replace that same ID before removal.
                self._sequence += 1
                self.scheduler.add_job(
                    self._run_tick,
                    "date",
                    run_date=when,
                    id=f"{WORKER}:{self._sequence}",
                )

    def _run_tick(self) -> None:
        if self._stopping.is_set():
            return
        try:
            tick_and_log(self.service)
        finally:
            # Date triggers deliberately implement fixed delay. Interval/cron
            # triggers would change the legacy timing and replay semantics.
            self._schedule(self.clock() + timedelta(seconds=self.interval))

    def run(self) -> None:
        self._schedule(self.clock())
        if not self._stopping.is_set():
            self.scheduler.start()

    def stop(self) -> None:
        with self._lock:
            self._stopping.set()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
