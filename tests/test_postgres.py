"""Real PostgreSQL conflict/rollback checks; only run against a disposable local test DB.

These tests deliberately do not implement a fake ingestion-worker or claim to
establish compatibility with the separate DERAI worker running on the server.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from derai_scheduler.config import Settings
from derai_scheduler.service import SchedulerService
from derai_scheduler.store import PostgreSQLStore

pytestmark = pytest.mark.postgres
TICK = datetime.fromisoformat("2026-11-13T11:37:20+07:00")

DDL = """
CREATE TABLE IF NOT EXISTS public.records (
    id varchar(36) PRIMARY KEY,
    tenant_id varchar(36) NOT NULL,
    workspace_id varchar(36) NOT NULL,
    kind varchar(40) NOT NULL,
    parent_id varchar(36),
    name varchar(300) NOT NULL,
    data text NOT NULL,
    status varchar(30) NOT NULL,
    idempotency_key varchar(200),
    created_at varchar(40) NOT NULL,
    CONSTRAINT uq_scope_kind_idem UNIQUE (tenant_id, workspace_id, kind, idempotency_key)
)
"""


@pytest.fixture
def database_engine():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable local PostgreSQL *_test database")
    url = make_url(database_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.query
    ):
        pytest.fail("TEST_DATABASE_URL must use PostgreSQL on loopback without query overrides")
    if not url.database or not (url.database.endswith("_test") or url.database.startswith("test_")):
        pytest.fail(
            "TEST_DATABASE_URL database must end in _test or start with test_; "
            "records will be cleared"
        )
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    # An explicit hostaddr prevents inherited libpq settings from overriding
    # the verified loopback hostname before this destructive fixture setup.
    hostaddr = "127.0.0.1" if url.host == "localhost" else url.host
    engine = create_engine(url, pool_pre_ping=True, connect_args={"hostaddr": hostaddr})
    with engine.begin() as connection:
        connection.execute(text(DDL))
        connection.execute(text("TRUNCATE TABLE public.records"))
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE public.records"))
        engine.dispose()


def insert_topic(
    engine,
    keywords=None,
    *,
    data=None,
    status="ready",
    kind="topic",
    tenant=None,
    workspace=None,
    topic_id=None,
):
    record = {
        "id": topic_id or str(uuid4()),
        "tenant_id": tenant or str(uuid4()),
        "workspace_id": workspace or str(uuid4()),
        "kind": kind,
        "name": "fixture-topic",
        "data": data
        if data is not None
        else json.dumps({"keywords": ["TNI", "Indonesia"] if keywords is None else keywords}),
        "status": status,
        "created_at": "2026-11-13T04:00:00+00:00",
    }
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO public.records
                (id, tenant_id, workspace_id, kind, name, data, status, created_at)
            VALUES (:id, :tenant_id, :workspace_id, :kind, :name, :data, :status, :created_at)
        """),
            record,
        )
    return record


def service(engine, **settings):
    return SchedulerService(
        PostgreSQLStore(engine), Settings(database_url="postgresql://unused", **settings)
    )


def jobs(engine):
    with engine.connect() as connection:
        return (
            connection.execute(
                text(
                    "SELECT * FROM public.records WHERE kind='job' "
                    "ORDER BY parent_id, name, idempotency_key"
                )
            )
            .mappings()
            .all()
        )


def test_postgres_example_and_repeat_after_failed_status(database_engine) -> None:
    insert_topic(database_engine, [" TNI ", "Indonesia", "tni", ""])
    scheduler = service(database_engine)
    assert scheduler.tick(now=TICK) == 4
    with database_engine.begin() as connection:
        connection.execute(text("UPDATE public.records SET status='failed' WHERE kind='job'"))
    assert scheduler.tick(now=TICK) == 0
    assert len(jobs(database_engine)) == 4
    assert {row["status"] for row in jobs(database_engine)} == {"failed"}


def test_postgres_two_overlapping_ticks_are_atomic_and_count_only_actual_inserts(
    database_engine,
) -> None:
    insert_topic(database_engine)
    barrier = threading.Barrier(2)

    class OverlapStore(PostgreSQLStore):
        def transaction(self):
            outer_context = super().transaction()

            class Context:
                def __enter__(self):
                    transaction = outer_context.__enter__()
                    barrier.wait(timeout=15)
                    return transaction

                def __exit__(self, exc_type, exc_value, traceback):
                    return outer_context.__exit__(exc_type, exc_value, traceback)

            return Context()

    def run_tick():
        return SchedulerService(
            OverlapStore(database_engine), Settings(database_url="postgresql://unused")
        ).tick(now=TICK)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_tick) for _ in range(2)]
        counts = [future.result(timeout=30) for future in futures]
    assert sorted(counts) == [0, 4]
    rows = jobs(database_engine)
    assert len(rows) == 4
    assert (
        len(
            {
                (row["tenant_id"], row["workspace_id"], row["kind"], row["idempotency_key"])
                for row in rows
            }
        )
        == 4
    )


@pytest.mark.parametrize("delete_name", ["social-media", "online-news"])
def test_postgres_only_missing_job_type_is_inserted(database_engine, delete_name: str) -> None:
    insert_topic(database_engine, ["TNI"])
    scheduler = service(database_engine)
    assert scheduler.tick(now=TICK) == 2
    with database_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM public.records WHERE kind='job' AND name=:name"),
            {"name": delete_name},
        )
    assert scheduler.tick(now=TICK) == 1
    assert {row["name"] for row in jobs(database_engine)} == {"social-media", "online-news"}


def test_postgres_bad_json_rolls_back_whole_tick(database_engine) -> None:
    insert_topic(database_engine, ["TNI"], topic_id="00000000-0000-4000-8000-000000000001")
    insert_topic(database_engine, data="not-json", topic_id="ffffffff-ffff-4fff-8fff-ffffffffffff")
    with pytest.raises((TypeError, ValueError)):
        service(database_engine).tick(now=TICK)
    assert jobs(database_engine) == []


def test_postgres_selects_only_non_deleting_topics(database_engine) -> None:
    insert_topic(database_engine, ["TNI"], status="deleting")
    insert_topic(database_engine, ["TNI"], kind="document")
    insert_topic(database_engine, [])
    active = insert_topic(database_engine, ["Indonesia"], status="draft")
    assert service(database_engine).tick(now=TICK) == 2
    assert {row["parent_id"] for row in jobs(database_engine)} == {active["id"]}


def test_postgres_scope_copy_unicode_and_hour_transition(database_engine) -> None:
    first = insert_topic(database_engine, [" Straße ", "STRASSE"])
    second = insert_topic(database_engine, ["Straße"])
    scheduler = service(database_engine, article_max_pages="3")
    assert scheduler.tick(now=TICK) == 4
    assert scheduler.tick(now=TICK + timedelta(hours=3)) == 4
    rows = jobs(database_engine)
    assert len(rows) == 8
    topics = {row["id"]: row for row in [first, second]}
    for row in rows:
        assert (row["tenant_id"], row["workspace_id"]) == (
            topics[row["parent_id"]]["tenant_id"],
            topics[row["parent_id"]]["workspace_id"],
        )
        assert ":16d96952087774fe:" in row["idempotency_key"]
        payload = json.loads(row["data"])
        assert payload["query"] == "Straße"
        if row["name"] == "online-news":
            assert payload["options"] == {"online_news": {"max_pages": "3"}}
    assert {json.loads(row["data"])["scheduled_for"] for row in rows} == {
        "2026-11-13T04:00:00+00:00",
        "2026-11-13T07:00:00+00:00",
    }


def test_postgres_worker_rls_scopes_and_idempotency(database_engine) -> None:
    # Use the existing Compose role without changing role membership, credentials, or attributes.
    with database_engine.connect() as connection:
        has_worker = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'derai_worker')")
        )
        if not has_worker:
            pytest.skip("The local Compose PostgreSQL cluster supplies the derai_worker role")
        pristine = connection.scalar(
            text("""
                SELECT NOT relrowsecurity
                   AND (relacl IS NULL OR relacl = acldefault('r', relowner))
                   AND NOT EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = pg_class.oid)
                FROM pg_class WHERE oid = 'public.records'::regclass
            """)
        )
        assert pristine, "RLS test requires the disposable fixture table without existing grants"

    tenant_a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    tenant_b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    workspace_a = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    workspace_b = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    first = insert_topic(database_engine, ["TNI"], tenant=tenant_a, workspace=workspace_a)
    second = insert_topic(database_engine, ["TNI"], tenant=tenant_b, workspace=workspace_b)
    # This would roll back the tick if the worker accidentally scanned the whole table.
    insert_topic(
        database_engine, data="out-of-scope invalid JSON", tenant=tenant_a, workspace=workspace_b
    )
    scope = f"""(tenant_id, workspace_id) IN (
        ('{tenant_a}', '{workspace_a}'), ('{tenant_b}', '{workspace_b}')
    )"""
    with database_engine.begin() as connection:
        connection.execute(text("GRANT SELECT, INSERT ON public.records TO derai_worker"))
        connection.execute(text("ALTER TABLE public.records ENABLE ROW LEVEL SECURITY"))
        connection.execute(
            text(f"""
            CREATE POLICY test_worker_select ON public.records FOR SELECT TO derai_worker
            USING ({scope})
        """)
        )
        connection.execute(
            text(f"""
            CREATE POLICY test_worker_insert ON public.records FOR INSERT TO derai_worker
            WITH CHECK (({scope}) AND kind = 'job' AND status = 'queued')
        """)
        )

    worker_engine = database_engine.execution_options()

    def use_worker_role(connection):
        connection.exec_driver_sql("SET LOCAL ROLE derai_worker")

    event.listen(worker_engine, "begin", use_worker_role)
    try:
        with worker_engine.begin() as connection:
            assert connection.execute(
                text("""
                SELECT current_user, row_security_active('public.records'::regclass),
                       has_table_privilege('public.records', 'SELECT'),
                       has_table_privilege('public.records', 'INSERT'),
                       has_table_privilege('public.records', 'UPDATE'),
                       has_table_privilege('public.records', 'DELETE')
            """)
            ).one() == ("derai_worker", True, True, True, False, False)

        scheduler = service(worker_engine)
        assert scheduler.tick(now=TICK) == 4
        original = jobs(database_engine)
        assert {(row["parent_id"], row["tenant_id"], row["workspace_id"]) for row in original} == {
            (first["id"], tenant_a, workspace_a),
            (second["id"], tenant_b, workspace_b),
        }
        assert all(row["status"] == "queued" for row in original)
        with database_engine.begin() as connection:
            connection.execute(text("UPDATE public.records SET status='failed' WHERE kind='job'"))
        assert scheduler.tick(now=TICK) == 0

        missing = next(
            row
            for row in original
            if row["parent_id"] == second["id"] and row["name"] == "online-news"
        )
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM public.records WHERE id=:id"), {"id": missing["id"]}
            )
        assert scheduler.tick(now=TICK) == 1
        assert scheduler.tick(now=TICK) == 0

        final = jobs(database_engine)
        assert {row["id"] for row in final if row["status"] == "failed"} == {
            row["id"] for row in original if row["id"] != missing["id"]
        }
        (replacement,) = [row for row in final if row["status"] == "queued"]
        assert replacement["id"] != missing["id"]
        assert replacement["idempotency_key"] == missing["idempotency_key"]
        assert replacement["parent_id"] == second["id"]
    finally:
        event.remove(worker_engine, "begin", use_worker_role)
        with database_engine.begin() as connection:
            connection.execute(text("DROP POLICY test_worker_select ON public.records"))
            connection.execute(text("DROP POLICY test_worker_insert ON public.records"))
            connection.execute(text("ALTER TABLE public.records DISABLE ROW LEVEL SECURITY"))
            connection.execute(text("REVOKE SELECT, INSERT ON public.records FROM derai_worker"))
