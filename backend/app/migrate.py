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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import models  # noqa: F401  — метадата бүртгүүлэх
from app.db import Base, init_engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def apply_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if engine.url.get_backend_name() != "postgresql":
        return

    sql = (MIGRATIONS_DIR / "postgres_append_only.sql").read_text(encoding="utf-8")
    async with engine.begin() as conn:
        for statement in [s.strip() for s in sql.split(";--split--") if s.strip()]:
            await conn.execute(text(statement))


async def _main() -> None:
    from app.config.settings import get_settings

    engine = init_engine(get_settings().DATABASE_URL)
    await apply_schema(engine)
    await engine.dispose()


if __name__ == "__main__":  # pragma: no cover - CLI
    asyncio.run(_main())
