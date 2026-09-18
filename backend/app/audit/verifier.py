"""Audit chain verifier (LLD §14.2, T-23, AC-19).

`seq` дарааллаар уншиж hash-ийг дахин тооцно. ЭХНИЙ зөрүүтэй `seq`-ийг
мэдээлж зогсоно — цааш үргэлжлүүлбэл нэг эвдрэл олон «алдаа» болж харагдана.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.audit.chain import GENESIS_HASH, compute_hash


@dataclass(frozen=True, slots=True)
class ChainBreak:
    seq: int
    detail: str


async def verify_chain(session: AsyncSession, *, from_seq: int = 1) -> ChainBreak | None:
    rows = (
        await session.execute(
            select(models.AuditLog).where(models.AuditLog.seq >= from_seq).order_by(models.AuditLog.seq)
        )
    ).scalars()

    prev_hash: bytes | None = None
    for row in rows:
        if prev_hash is None:
            # Хэсэгчилсэн шалгалт эхэлж буй мөрийн prev_hash-ыг үнэн гэж үзнэ;
            # бүтэн шалгалтад эхний мөр нь ЗААВАЛ genesis-т холбогдоно.
            if from_seq <= 1 and row.prev_hash != GENESIS_HASH:
                return ChainBreak(int(row.seq), "эхний мөр genesis-т холбогдоогүй")
            prev_hash = row.prev_hash
        if row.prev_hash != prev_hash:
            return ChainBreak(int(row.seq), "prev_hash өмнөх мөрийн hash-тай таарахгүй")
        expected = compute_hash(
            row.prev_hash, int(row.seq), row.ts, row.event_type, row.actor, row.payload
        )
        if expected != row.hash:
            return ChainBreak(int(row.seq), "мөрийн агуулга hash-тайгаа таарахгүй")
        prev_hash = row.hash
    return None


async def _main() -> int:  # pragma: no cover - CLI
    import argparse

    from app.config.settings import get_settings
    from app.db import init_engine, make_sessionmaker

    parser = argparse.ArgumentParser(description="audit_log-ийн hash chain шалгагч")
    parser.add_argument("--from", dest="from_seq", type=int, default=1)
    args = parser.parse_args()

    engine = init_engine(get_settings().DATABASE_URL)
    async with make_sessionmaker(engine)() as session:
        result = await verify_chain(session, from_seq=args.from_seq)
    await engine.dispose()
    if result is None:
        print("chain бүрэн бүтэн")
        return 0
    print(f"ЭВДЭРСЭН seq={result.seq}: {result.detail}")
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(asyncio.run(_main()))
