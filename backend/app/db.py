"""DB engine / session / Base.

Prod нь Postgres (`postgresql+asyncpg`), тест нь SQLite — ижил ORM метадата.
Postgres-д хамаарах хэсгүүд (audit_log-ийн UPDATE/DELETE татгалзах RULE) нь
`migrations/`-д тусад нь, `dialect == 'postgresql'` нөхцөлтэй.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from datetime import UTC, datetime

from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator):
    """`timestamptz` — уншихад ЗААВАЛ tz-aware (AC-26).

    SQLite нь tzinfo-г хадгалдаггүй тул наад талаас naive datetime буцаана.
    Naive утга нь домэйнд алдаа гэж тодорхойлогдсон учир энэ давхарга дээр
    UTC-г ил сэргээнэ — «хаанаас ирснийг мэдэхгүй цаг» гэсэн байдал үүсэхгүй.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"naive datetime хоригтой: {value!r}")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def make_engine(url: str) -> AsyncEngine:
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, **kwargs)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


_ENGINE: AsyncEngine | None = None
_SESSIONMAKER: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str) -> AsyncEngine:
    global _ENGINE, _SESSIONMAKER
    _ENGINE = make_engine(url)
    _SESSIONMAKER = make_sessionmaker(_ENGINE)
    return _ENGINE


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _SESSIONMAKER is None:  # pragma: no cover - тохиргооны алдаа
        raise RuntimeError("init_engine() дуудагдаагүй")
    return _SESSIONMAKER


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session


async def enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """SQLite-д FK анхдагчаар унтраалттай — тест Postgres-тэй ижил байх ёстой."""
    if engine.url.get_backend_name() != "sqlite":
        return
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_pragma(dbapi_conn, _record):  # pragma: no cover - event hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
