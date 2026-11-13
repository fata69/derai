"""Scheduling lifecycle and sanitized observability, without waiting real minutes."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from derai_scheduler.runtime import FixedDelayRunner, tick_and_log


class RecordingScheduler:
    def __init__(self):
        self.jobs = []
        self.running = False
        self.start_count = 0
        self.shutdown_count = 0

    def add_job(self, function, trigger, **options):
        self.jobs.append((function, trigger, options))

    def start(self):
        self.start_count += 1
        self.running = True

    def shutdown(self, *, wait):
        assert wait is True
        self.shutdown_count += 1
        self.running = False


class StubService:
    def __init__(self, processed=4, error=None, on_tick=None):
        self.processed = processed
        self.error = error
        self.on_tick = on_tick
        self.calls = []

    def tick(self, now=None):
        self.calls.append(now)
        if self.on_tick:
            self.on_tick()
        if self.error:
            raise self.error
        return self.processed


def test_first_tick_is_scheduled_immediately_at_startup() -> None:
    start = datetime(2026, 11, 13, 4, 37, 20, tzinfo=UTC)
    runner = FixedDelayRunner(StubService(), 60, clock=lambda: start)
    scheduler = RecordingScheduler()
    runner.scheduler = scheduler
    runner.run()
    assert scheduler.start_count == 1
    assert len(scheduler.jobs) == 1
    _, trigger, options = scheduler.jobs[0]
    assert trigger == "date"
    assert options["run_date"] == start


@pytest.mark.parametrize("error", [None, RuntimeError("private secret in failure")])
def test_next_tick_is_sixty_seconds_after_completion_even_on_failure(error, capsys) -> None:
    start = datetime(2026, 11, 13, 4, 37, 20, tzinfo=UTC)
    completion = start + timedelta(seconds=17)
    current = [start]
    service = StubService(error=error, on_tick=lambda: current.__setitem__(0, completion))
    runner = FixedDelayRunner(service, 60, clock=lambda: current[0])
    scheduler = RecordingScheduler()
    runner.scheduler = scheduler
    runner.run()
    scheduler.jobs[0][0]()
    assert len(service.calls) == 1
    assert len(scheduler.jobs) == 2
    _, trigger, options = scheduler.jobs[1]
    assert trigger == "date"
    assert options["run_date"] == completion + timedelta(seconds=60)
    assert options["run_date"] != start + timedelta(seconds=60)
    assert scheduler.jobs[0][2]["id"] != scheduler.jobs[1][2]["id"]
    record = json.loads(capsys.readouterr().out)
    assert record["worker"] == "collection-scheduler"
    assert ("error" in record) is (error is not None)


def test_stop_prevents_further_ticks_and_reschedules() -> None:
    service = StubService()
    runner = FixedDelayRunner(service, 60)
    scheduler = RecordingScheduler()
    runner.scheduler = scheduler
    runner.run()
    runner.stop()
    runner._run_tick()
    runner.stop()
    assert scheduler.shutdown_count == 1
    assert len(scheduler.jobs) == 1
    assert service.calls == []


def test_real_apscheduler_runs_multiple_fast_ticks_and_stops_cleanly(capsys) -> None:
    """Exercise actual date-job removal/rescheduling; a same-ID race loses later ticks."""
    reached_three = threading.Event()
    counter = [0]
    errors = []

    def record_tick():
        counter[0] += 1
        if counter[0] >= 3:
            reached_three.set()

    runner = FixedDelayRunner(StubService(on_tick=record_tick), 0.01)

    def run():
        try:
            runner.run()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, name="scheduler-smoke", daemon=True)
    thread.start()
    try:
        assert reached_three.wait(timeout=5), "The actual scheduler lost a successive tick"
    finally:
        runner.stop()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors == []
    assert counter[0] >= 3
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(records) == counter[0]
    assert all(record == {"worker": "collection-scheduler", "processed": 4} for record in records)


SECRET = "private-topic-sk-secret-password"


@pytest.mark.parametrize(
    "error",
    [
        json.JSONDecodeError("malformed", SECRET, 0),
        OperationalError("SELECT secret_data", {"password": SECRET}, RuntimeError(SECRET)),
        ValueError(f"postgresql://user:{SECRET}@localhost/database"),
        OSError(SECRET),
        RuntimeError(SECRET),
    ],
)
def test_failure_logs_type_and_safe_message_without_credentials_or_topic(error, capsys) -> None:
    assert tick_and_log(StubService(error=error)) is False
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert "SELECT secret_data" not in captured.out + captured.err
    assert "postgresql://" not in captured.out + captured.err
    assert captured.err == ""
    record = json.loads(captured.out)
    assert set(record) == {"worker", "error", "message"}
    assert record["worker"] == "collection-scheduler"
    assert record["error"] == type(error).__name__
    assert record["message"]


def test_success_log_is_the_prd_processed_record(capsys) -> None:
    tick_time = datetime(2026, 11, 13, 4, 37, tzinfo=UTC)
    service = StubService(processed=0)
    assert tick_and_log(service, tick_time) is True
    assert service.calls == [tick_time]
    assert json.loads(capsys.readouterr().out) == {"worker": "collection-scheduler", "processed": 0}
