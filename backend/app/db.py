"""Database engine, per-request sessions, and the shared UTC datetime column type."""

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import settings


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Stores datetimes as naive UTC (SQLite has no time zones) and always returns them as aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"Refusing to store naive datetime {value!r}; pass a timezone-aware datetime")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _configure_sqlite_connection(dbapi_connection: Any, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    # SQLite ignores foreign keys unless this is switched on for every new connection.
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL lets the UI keep reading while background generation jobs write.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def make_engine(database_url: str, **engine_options: Any) -> Engine:
    # check_same_thread=False: FastAPI and the generation jobs use sessions from worker threads.
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, **engine_options)
    event.listen(engine, "connect", _configure_sqlite_connection)
    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session
