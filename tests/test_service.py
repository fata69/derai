"""Tick atomicity and idempotency using an independent transactional test store."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from derai_scheduler.config import Settings
from derai_scheduler.domain import Topic, build_jobs
from derai_scheduler.service import SchedulerService

TICK = datetime.fromisoformat("2026-11-13T11:37:20+07:00")
SETTINGS = Settings(database_url="postgresql://unused", enabled=True)


def topic(
    topic_id: str = "topic-1",
    keywords: list | None = None,
    *,
    tenant: str = "tenant-1",
    workspace: str = "workspace-1",
) -> Topic:
    return Topic(
        topic_id,
        tenant,
        workspace,
        json.dumps({"keywords": ["TNI", "Indonesia"] if keywords is None else keywords}),
    )


class MemoryStore:
    """Staged rows are persisted only after the entire tick exits successfully."""

    def __init__(
        self, topics: list[Topic], *, fail_insert_at: int | None = None, fail_commit: bool = False
    ):
        self.topics = topics
        self.jobs = []
        self.transaction_count = 0
        self.fetch_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_insert_at = fail_insert_at
        self.fail_commit = fail_commit

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        pending = list(self.jobs)
        inserts = 0
        outer = self

        class Transaction:
            def fetch_topics(self):
                outer.fetch_count += 1
                return outer.topics

            def insert_job(self, job):
                nonlocal inserts
                inserts += 1
                if outer.fail_insert_at == inserts:
                    raise RuntimeError("simulated insert failure")
                key = (job.tenant_id, job.workspace_id, job.kind, job.idempotency_key)
                if any(
                    (old.tenant_id, old.workspace_id, old.kind, old.idempotency_key) == key
                    for old in pending
                ):
                    return False
                pending.append(job)
                return True

        try:
            yield Transaction()
            if self.fail_commit:
                raise RuntimeError("simulated commit failure")
        except BaseException:
            self.rollback_count += 1
            raise
        else:
            self.jobs = pending
            self.commit_count += 1


def test_successful_tick_commits_once_and_counts_new_rows_only() -> None:
    store = MemoryStore([topic()])
    service = SchedulerService(store, SETTINGS)
    assert service.tick(now=TICK) == 4
    assert len(store.jobs) == 4
    assert store.commit_count == 1
    assert service.tick(now=TICK) == 0
    assert len(store.jobs) == 4
    assert store.commit_count == 2


def test_failed_jobs_still_prevent_duplicates() -> None:
    store = MemoryStore([topic()])
    store.jobs = [replace(job, status="failed") for job in build_jobs(topic(), TICK)]
    assert SchedulerService(store, SETTINGS).tick(now=TICK) == 0
    assert {job.status for job in store.jobs} == {"failed"}


@pytest.mark.parametrize("existing_name", ["social-media", "online-news"])
def test_existing_one_type_does_not_block_missing_type(existing_name: str) -> None:
    one_keyword = topic(keywords=["TNI"])
    store = MemoryStore([one_keyword])
    store.jobs = [job for job in build_jobs(one_keyword, TICK) if job.name == existing_name]
    assert SchedulerService(store, SETTINGS).tick(now=TICK) == 1
    assert {job.name for job in store.jobs} == {"social-media", "online-news"}


def test_bad_topic_rolls_back_jobs_prepared_from_previous_topics() -> None:
    store = MemoryStore([topic(), Topic("broken", "tenant-1", "workspace-1", "broken JSON")])
    with pytest.raises((TypeError, ValueError)):
        SchedulerService(store, SETTINGS).tick(now=TICK)
    assert store.jobs == []
    assert store.commit_count == 0
    assert store.rollback_count == 1


def test_insert_error_rolls_back_entire_tick() -> None:
    store = MemoryStore([topic()], fail_insert_at=3)
    with pytest.raises(RuntimeError, match="insert failure"):
        SchedulerService(store, SETTINGS).tick(now=TICK)
    assert store.jobs == []
    assert store.rollback_count == 1
    assert store.commit_count == 0


def test_commit_error_does_not_report_processed_success() -> None:
    store = MemoryStore([topic()], fail_commit=True)
    with pytest.raises(RuntimeError, match="commit failure"):
        SchedulerService(store, SETTINGS).tick(now=TICK)
    assert store.jobs == []
    assert store.rollback_count == 1


def test_disabled_flag_performs_no_database_work() -> None:
    store = MemoryStore([topic()])
    disabled = replace(SETTINGS, enabled=False)
    assert SchedulerService(store, disabled).tick(now=TICK) == 0
    assert store.transaction_count == store.fetch_count == store.commit_count == 0


def test_empty_topic_set_commits_one_empty_tick() -> None:
    store = MemoryStore([])
    assert SchedulerService(store, SETTINGS).tick(now=TICK) == 0
    assert store.commit_count == 1


def test_keywords_added_during_hour_create_only_new_pairs() -> None:
    store = MemoryStore([topic(keywords=["TNI"])])
    service = SchedulerService(store, SETTINGS)
    assert service.tick(now=TICK) == 2
    store.topics = [topic(keywords=["TNI", "Indonesia"])]
    assert service.tick(now=TICK + timedelta(minutes=1)) == 2
    assert len(store.jobs) == 4


def test_skipped_hours_are_not_backfilled() -> None:
    store = MemoryStore([topic(keywords=["TNI"])])
    service = SchedulerService(store, SETTINGS)
    assert service.tick(now=TICK) == 2
    assert service.tick(now=TICK + timedelta(hours=5)) == 2
    hours = {json.loads(job.data)["scheduled_for"] for job in store.jobs}
    assert hours == {"2026-11-13T04:00:00+00:00", "2026-11-13T09:00:00+00:00"}


def test_each_tenant_workspace_and_topic_keeps_its_own_jobs() -> None:
    store = MemoryStore(
        [
            topic("topic-a", ["TNI"], tenant="tenant-a", workspace="workspace-a"),
            topic("topic-b", ["TNI"], tenant="tenant-b", workspace="workspace-b"),
            topic("topic-c", ["TNI"], tenant="tenant-a", workspace="workspace-c"),
        ]
    )
    assert SchedulerService(store, SETTINGS).tick(now=TICK) == 6
    assert {(job.parent_id, job.tenant_id, job.workspace_id) for job in store.jobs} == {
        ("topic-a", "tenant-a", "workspace-a"),
        ("topic-b", "tenant-b", "workspace-b"),
        ("topic-c", "tenant-a", "workspace-c"),
    }


def test_tick_uses_start_hour_even_when_writes_cross_hour_boundary() -> None:
    start = datetime.fromisoformat("2026-11-13T04:59:59+00:00")
    write = datetime.fromisoformat("2026-11-13T05:00:01+00:00")
    readings = iter([start, write, write])
    store = MemoryStore([topic(keywords=["TNI"])])
    scheduler = SchedulerService(store, SETTINGS, clock=lambda: next(readings))
    assert scheduler.tick() == 2
    assert {json.loads(job.data)["scheduled_for"] for job in store.jobs} == {
        "2026-11-13T04:00:00+00:00"
    }
    assert {datetime.fromisoformat(job.created_at) for job in store.jobs} == {write}
