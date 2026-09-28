"""Schema migration runner (T-02, ID=629).

**Яагаад Alembic биш:** DDL-ийн эх сурвалж НЭГ байх ёстой. ORM метадата + тусдаа
Alembic revision нь хоёр эх болж, зөрүү нь чимээгүй хуримтлагдана. Энд метадата
нь цорын ганц эх; Postgres-д зөвхөн ORM-оор илэрхийлэгдэхгүй зүйлс
(`audit_log`-ийн UPDATE/DELETE татгалзах RULE, GRANT) нь `migrations/*.sql`-д
нэмэлтээр ажиллана.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.schema import CreateColumn

from app import models  # noqa: F401  — метадата бүртгүүлэх
from app.db import Base, init_engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _add_missing_columns(conn) -> None:
    """`create_all` нь БАЙГАА хүснэгтэд шинэ багана НЭМЭХГҮЙ.

    Postgres-ийн `.sql` нь зөвхөн Postgres дээр ажилладаг тул хуучин SQLite
    файл (анхдагч `DATABASE_URL`) дээр `orders.entry_price` мөнхөд дутуу
    үлдэж байв. Тиймээс нэмэлтийг backend-ээс ХАМААРАХГҮЙ болгов: метадатад
    байгаа ч хүснэгтэд байхгүй багана бүрийг энд нэмнэ.
    """
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    preparer = conn.dialect.identifier_preparer
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = CreateColumn(column).compile(dialect=conn.dialect)
            conn.execute(
                text(f"ALTER TABLE {preparer.format_table(table)} ADD COLUMN {ddl}")
            )


async def apply_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)

    if engine.url.get_backend_name() != "postgresql":
        return

    sql = (MIGRATIONS_DIR / "postgres_append_only.sql").read_text(encoding="utf-8")
    async with engine.begin() as conn:
        # asyncpg-ийн prepared-statement зам нь dollar-quoted функцийн биен
        # дээр `TypeError: expected string or bytes-like object, got 'NoneType'`
        # гэж унадаг (status message нь None). Driver-ийн simple query
        # protocol-оор файлыг БҮХЭЛД нь нэг гүйлгээнд ажиллуулна — `;--split--`
        # нь SQL-ийн энгийн мөрийн тайлбар тул файл өөрөө хүчинтэй SQL.
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute(sql)


async def _main() -> None:
    from app.config.settings import get_settings

    engine = init_engine(get_settings().DATABASE_URL)
    await apply_schema(engine)
    await engine.dispose()


if __name__ == "__main__":  # pragma: no cover - CLI
    asyncio.run(_main())
