"""Research symbol watchlist (T-99, хувийн төсөл, LLD-д тусгаагүй).

Operator-ийн UI-аас сонгосон дэд жагсаалт л скан хийгдэнэ — том 20
symbol-той тулгарахгүй, зөвхөн сонирхсон хэдэн нь. `settings.RESEARCH_SYMBOLS`
бол ХАМГИЙН ИХ БОЛОМЖИТ олонлог; watchlist нь тэрний дэд олонлог л байж
болно (шинэ, тохируулаагүй symbol нэмэгдэхгүй).
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.api.attribution import _normalize
from app.util.time import now_utc

WATCHLIST_ID = 1


async def _benched(session: AsyncSession) -> set[str]:
    """Сүүлийн 2 хаалт нь цэвэр алдагдалтай, хамгийн сүүлийнх нь 24 цагийн
    дотор бол тухайн symbol нэг цикл завсарлана. Моделд «бүү хүр» гэж
    хэлэхгүй — жагсаалтад нь ердөө байхгүй тул propose_order хүрэхгүй.
    """
    # ponytail: 2 losses / 24h is a heuristic with nothing behind it — a knob to tune once a few dozen real closes exist.
    closed_at = func.coalesce(models.Order.filled_at, models.Order.submitted_at)
    rows = (
        await session.execute(
            select(models.Order.symbol, models.Order.realized_pl, closed_at)
            .where(models.Order.realized_pl.is_not(None))
            .order_by(closed_at.desc())
        )
    ).all()

    closes: dict[str, list[tuple]] = {}
    for symbol, pl, ts in rows:
        closes.setdefault(_normalize(symbol), []).append((pl, ts))

    cutoff = now_utc() - timedelta(hours=24)
    return {
        symbol
        for symbol, recent in closes.items()
        if len(recent) >= 2 and recent[0][1] >= cutoff and recent[0][0] + recent[1][0] < 0
    }


async def get_active_symbols(session: AsyncSession, settings) -> list[str]:
    row = await session.get(models.ResearchWatchlist, WATCHLIST_ID)
    allowed = set(settings.research_symbols)
    selected = (
        settings.research_symbols
        if row is None or not row.symbols.strip()
        else [s.strip().upper() for s in row.symbols.split(",") if s.strip()]
    )
    benched = await _benched(session)
    filtered = [s for s in selected if s in allowed and _normalize(s) not in benched]
    # Бүгд завсарлавал хоосон цикл болохын оронд бүтэн жагсаалт руу буцна.
    return filtered or settings.research_symbols


async def set_active_symbols(
    session: AsyncSession, symbols: list[str], settings
) -> list[str]:
    allowed = set(settings.research_symbols)
    cleaned = [s.strip().upper() for s in symbols if s.strip().upper() in allowed]
    if not cleaned:
        raise ValueError("тохиргоонд байхгүй symbol эсвэл хоосон жагсаалт")
    row = await session.get(models.ResearchWatchlist, WATCHLIST_ID)
    if row is None:
        row = models.ResearchWatchlist(
            id=WATCHLIST_ID, symbols=",".join(cleaned), updated_at=now_utc()
        )
        session.add(row)
    else:
        row.symbols = ",".join(cleaned)
        row.updated_at = now_utc()
    await session.commit()
    return cleaned
