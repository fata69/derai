"""SQLAlchemy adapter; the scheduler never creates tables or changes existing jobs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, Engine, make_url

from .config import Settings
from .domain import Job, Topic

metadata = MetaData()
records = Table(
    "records",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(36), nullable=False),
    Column("workspace_id", String(36), nullable=False),
    Column("kind", String(40), nullable=False),
    Column("parent_id", String(36)),
    Column("name", String(300)),
    Column("data", Text),
    Column("status", String(30)),
    Column("idempotency_key", String(200)),
    Column("created_at", String(40)),
    schema="public",
)


def create_database_engine(settings: Settings) -> Engine:
    if not settings.database_url:
        raise ValueError("DATABASE_URL is required for PostgreSQL operations")
    url = make_url(settings.database_url)
    if url.get_backend_name() not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must point to PostgreSQL")
    # Accept the legacy postgresql:// format while selecting psycopg 3 explicitly.
    url = url.set(drivername="postgresql+psycopg")
    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 10, "application_name": "collection-scheduler"},
    )


class PostgreSQLTransaction:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def fetch_topics(self) -> Iterator[Topic]:
        statement = (
            select(records.c.id, records.c.tenant_id, records.c.workspace_id, records.c.data)
            .where(records.c.kind == "topic", records.c.status != "deleting")
            .order_by(records.c.id)
        )
        for row in self.connection.execute(statement).mappings():
            yield Topic(**row)

    def insert_job(self, job: Job) -> bool:
        statement = (
            insert(records)
            .values(**asdict(job))
            .on_conflict_do_nothing(constraint="uq_scope_kind_idem")
            .returning(records.c.id)
        )
        return self.connection.execute(statement).scalar_one_or_none() is not None


class PostgreSQLStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def transaction(self) -> Iterator[PostgreSQLTransaction]:
        with self.engine.begin() as connection:
            yield PostgreSQLTransaction(connection)
