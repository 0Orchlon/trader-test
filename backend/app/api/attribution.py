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

#: Ширхэг ЦААШИД ХӨДӨЛӨХГҮЙ төлөвүүд. Бусад БҮГД нь «амьд».
TERMINAL_STATUSES = (
    OrderStatus.REJECTED,
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.EXPIRED,
    # `failed` нь энд: EOD тулгалт (`reconcile.LOCAL_OPEN_STATUSES`) түүнийг
    # broker-ийн үнэнээр ЗАСНА. Амьд гэж үзвэл хүрээгүй submit-ийн мөр тухайн
    # symbol-ын хаалтыг ҮҮРД хориглоно.
    OrderStatus.FAILED,
)
#: Хаалтын хаалга УРВУУГААР бодогдоно: enum-д шинэ төлөв нэмэгдвэл анхдагчаар
#: «амьд» тул хоригдоно — чимээгүй хамгаалалтгүй үлдэхгүй (`pending_risk` нь
#: `OPEN_ORDER_STATUSES`-д байхгүй тул яг ингэж алдагдсан).
LIVE_STATUSES = tuple(s.value for s in OrderStatus if s not in TERMINAL_STATUSES)


def _normalize(symbol: str) -> str:
    """Alpaca-ийн `/v2/positions` нь crypto symbol-оос `/`-г хасдаг
    (`BTC/USD` → `BTCUSD`), харин order/quote тал `/`-тэй хэвээр (T-99,
    эмпирик ажиглалт) — харьцуулахад л normalize хийнэ, харуулах утгыг
    ХЭЗЭЭ Ч өөрчлөхгүй (AC-1-ийн сүнс)."""
    return symbol.replace("/", "")


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
        by_symbol.setdefault(_normalize(row.symbol), []).append(row)

    out: dict[str, Attribution] = {}
    for symbol, orders in by_symbol.items():
        # Локал order-ууд тэглэгдсэн бол (buy − sell = 0) энэ symbol дээрх позиц
        # МАНАЙХ БИШ: хуучин хаагдсан fill ирээдүйн позицийг эзэмшихгүй —
        # `external`-д унана (LLD D-1).
        if sum((o.filled_qty if o.side == "buy" else -o.filled_qty) for o in orders) == 0:
            continue
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
    return origins.get(_normalize(position.symbol), EXTERNAL)


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
            last_decision[_normalize(symbol)] = decision

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
        return _normalize(symbol) in origins and origins[_normalize(symbol)].mixed

    for order in open_orders:
        entry = slot(order.origin, order.origin_detail, order.symbol)
        entry["open_order_count"] += 1
        entry["origin_mixed"] = mixed(order.symbol)

    for position in positions:
        attribution = origins.get(_normalize(position.symbol), EXTERNAL)
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
                    last_decision[_normalize(symbol)].created_at
                    if _normalize(symbol) in last_decision
                    else None
                ),
                last_decision_id=(
                    str(last_decision[_normalize(symbol)].id)
                    if _normalize(symbol) in last_decision
                    else None
                ),
            )
            for symbol, data in sorted(symbols.items())
        ]
        out.append((Origin(origin), detail, rows))
    # Мөргүй бүлэг үүсгэхгүй (contracts.yaml `AttributionEnvelope`).
    return [group for group in out if group[2]]
