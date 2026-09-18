"""Attribution resolver (T-46, LLD §11, AC-29, AC-30).

Alpaca нь position-д `client_order_id` өгдөггүй. Тиймээс тухайн symbol дээрх
ХАМГИЙН СҮҮЛИЙН filled локал order-оор origin тогтооно. Локал fill байхгүй бол
`external` — «хамгийн ойрын order-т наах» таамаг БАЙХГҮЙ (LLD D-1).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.broker.models import OPEN_ORDER_STATUSES, Origin, OrderStatus, Position

FILLED_STATUSES = (OrderStatus.FILLED.value, OrderStatus.PARTIALLY_FILLED.value)
OPEN_STATUSES = tuple(s.value for s in OPEN_ORDER_STATUSES)


@dataclass(frozen=True, slots=True)
class Attribution:
    origin: Origin
    origin_detail: str | None
    #: Нэг symbol дээр олон origin fill хийсэн бол UI ил тэмдэглэнэ (LLD §16.4).
    mixed: bool = False
    #: Тухайн symbol дээр fill хийсэн БҮХ (origin, detail) хос — сүүлийнх нь
    #: эхэнд. Холимог symbol-ыг бүх картад гаргахад хэрэглэнэ (LLD §16.4).
    pairs: tuple[tuple[str, str | None], ...] = ()


EXTERNAL = Attribution(Origin.EXTERNAL, None, pairs=((Origin.EXTERNAL.value, None),))


async def position_origins(session: AsyncSession) -> dict[str, Attribution]:
    rows = (
        await session.execute(
            select(models.Order)
            .where(models.Order.status.in_(FILLED_STATUSES))
            .order_by(models.Order.submitted_at)
        )
    ).scalars().all()

    by_symbol: dict[str, list[models.Order]] = {}
    for row in rows:
        by_symbol.setdefault(row.symbol, []).append(row)

    out: dict[str, Attribution] = {}
    for symbol, orders in by_symbol.items():
        latest = max(orders, key=lambda o: (o.filled_at or o.submitted_at))
        newest_first = (latest.origin, latest.origin_detail)
        pairs = [newest_first] + sorted(
            {(o.origin, o.origin_detail) for o in orders} - {newest_first},
            key=lambda pair: (pair[0], pair[1] or ""),
        )
        out[symbol] = Attribution(
            origin=Origin(latest.origin),
            origin_detail=latest.origin_detail,
            mixed=len(pairs) > 1,
            pairs=tuple(pairs),
        )
    return out


def attribute(position: Position, origins: dict[str, Attribution]) -> Attribution:
    return origins.get(position.symbol, EXTERNAL)


@dataclass(frozen=True, slots=True)
class SymbolRow:
    symbol: str
    has_open_position: bool
    position_qty: Decimal | None
    market_value: Decimal | None
    open_order_count: int
    origin_mixed: bool
    last_decision_at: datetime | None
    last_decision_id: str | None


async def build_groups(
    session: AsyncSession, positions: list[Position]
) -> list[tuple[Origin, str | None, list[SymbolRow]]]:
    """`GET /attribution`-ийн бие.

    Гаралтын symbol олонлог нь `orders` ∪ `positions`-ийн symbol олонлогтой
    ЯГ тэнцүү (T-46 DoD б). Тусдаа кэш БАЙХГҮЙ — мөр бүр бодит мөрөөс.
    """
    origins = await position_origins(session)

    open_orders = (
        await session.execute(
            select(models.Order).where(models.Order.status.in_(OPEN_STATUSES))
        )
    ).scalars().all()

    decisions = (
        await session.execute(
            select(models.AgentDecision).order_by(models.AgentDecision.created_at)
        )
    ).scalars().all()
    last_decision: dict[str, models.AgentDecision] = {}
    for decision in decisions:
        symbol = (decision.proposal or {}).get("symbol")
        if symbol:
            last_decision[symbol] = decision

    # (origin, origin_detail) → symbol → SymbolRow-ийн түүхий хэсгүүд
    grouped: dict[tuple[str, str | None], dict[str, dict]] = {}

    def slot(origin: str, detail: str | None, symbol: str) -> dict:
        bucket = grouped.setdefault((origin, detail), {})
        return bucket.setdefault(
            symbol,
            {
                "has_open_position": False,
                "position_qty": None,
                "market_value": None,
                "open_order_count": 0,
                "origin_mixed": False,
            },
        )

    def mixed(symbol: str) -> bool:
        return symbol in origins and origins[symbol].mixed

    for order in open_orders:
        entry = slot(order.origin, order.origin_detail, order.symbol)
        entry["open_order_count"] += 1
        entry["origin_mixed"] = mixed(order.symbol)

    for position in positions:
        attribution = origins.get(position.symbol, EXTERNAL)
        # Холимог symbol нь ХОЛБОГДОХ БҮХ картад гарна — далдлахгүй (LLD §16.4).
        # Позицийн ширхэг/дүн нь давхардана: задаргаа биш, оролцоо гэсэн утгатай
        # тул `origin_mixed` тэмдэг заавал хамт явна.
        for origin, detail in attribution.pairs:
            entry = slot(origin, detail, position.symbol)
            entry["has_open_position"] = True
            entry["position_qty"] = position.qty
            entry["market_value"] = position.market_value
            entry["origin_mixed"] = attribution.mixed

    out: list[tuple[Origin, str | None, list[SymbolRow]]] = []
    for (origin, detail), symbols in grouped.items():
        rows = [
            SymbolRow(
                symbol=symbol,
                has_open_position=data["has_open_position"],
                position_qty=data["position_qty"],
                market_value=data["market_value"],
                open_order_count=data["open_order_count"],
                origin_mixed=data["origin_mixed"],
                last_decision_at=(
                    last_decision[symbol].created_at if symbol in last_decision else None
                ),
                last_decision_id=(
                    str(last_decision[symbol].id) if symbol in last_decision else None
                ),
            )
            for symbol, data in sorted(symbols.items())
        ]
        out.append((Origin(origin), detail, rows))
    # Мөргүй бүлэг үүсгэхгүй (contracts.yaml `AttributionEnvelope`).
    return [group for group in out if group[2]]
