"""One atomic tick, independent of the scheduling framework and database driver."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from .config import Settings
from .domain import Job, Topic, build_jobs, utc_now


class Transaction(Protocol):
    def fetch_topics(self) -> Iterable[Topic]: ...

    def insert_job(self, job: Job) -> bool: ...


class Store(Protocol):
    def transaction(self) -> AbstractContextManager[Transaction]: ...


class SchedulerService:
    def __init__(
        self, store: Store, settings: Settings, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.store = store
        self.settings = settings
        self.clock = clock

    def tick(self, now: datetime | None = None) -> int:
        tick_time = now if now is not None else self.clock()
        if not self.settings.enabled:
            return 0
        processed = 0
        # One connection and one transaction for the whole tick. A parse failure
        # anywhere rolls back jobs already inserted for earlier topics.
        with self.store.transaction() as transaction:
            for topic in transaction.fetch_topics():
                for job in build_jobs(
                    topic, tick_time, self.settings.article_max_pages, clock=self.clock
                ):
                    processed += int(transaction.insert_job(job))
        return processed
