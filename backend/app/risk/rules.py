"""Risk-ийн дүрмүүд — дүрэм тус бүр НЭГ функц (LLD §8.1).

Дүрмийн дараалал ТОГТМОЛ. Эхний унасан нь шийдэхгүй — **бүх** дүрэм ажиллаж
`checks[]` бүрэн бөглөгдөнө: operator юу унасныг бүхэлд нь харна.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.broker.models import OrderIntent, OrderSide, Position, PositionSide, SystemState
from app.risk.limits import PDT_EQUITY_FLOOR
from app.util.money import money_str


@dataclass(frozen=True, slots=True)
class Check:
    rule: str
    passed: bool
    limit_name: str | None = None
    limit_value: str | None = None
    actual_value: str | None = None
    detail: str | None = None


def position_for(positions: list[Position], symbol: str) -> Position | None:
    for p in positions:
        if p.symbol == symbol:
            return p
    return None


def reference_price(ctx, req: OrderIntent) -> Decimal | None:
    """Notional тооцох лавлах үнэ. Quote байхгүй бол ТААМАГЛАХГҮЙ."""
    if req.limit_price is not None:
        return req.limit_price
    if ctx.quote is None:
        return None
    return ctx.quote.last


def increases_exposure(pos: Position | None, req: OrderIntent) -> bool:
    """LLD §8.2 — «exposure нэмэгдүүлэх»-ийн ЯГ тодорхойлолт (AC-35)."""
    if pos is None:
        return True  # шинэ symbol
    if pos.side is PositionSide.LONG and req.side is OrderSide.BUY:
        return True  # нэмж авах
    if pos.side is PositionSide.SHORT and req.side is OrderSide.SELL:
        return True  # нэмж богиносгох
    # Эсрэг тийш: хаалт эсвэл эргүүлэлт. Хэтрүүлэн эргүүлэх нь нэмэгдүүлэлт.
    return req.qty > abs(pos.qty)


# --- R1…R9 ---


def r1_system_state(ctx, req: OrderIntent) -> Check:
    passed = ctx.system_state is not SystemState.HALTED
    return Check(
        rule="system_state",
        passed=passed,
        limit_name="SYSTEM_STATE",
        limit_value="active|winding_down",
        actual_value=ctx.system_state.value,
        detail=None if passed else "Систем halted — шинэ order илгээхгүй",
    )


def r2_wind_down_direction(ctx, req: OrderIntent) -> Check:
    if ctx.system_state is not SystemState.WINDING_DOWN:
        return Check(
            rule="wind_down_direction",
            passed=True,
            detail="winding_down биш — энэ дүрэм хамаарахгүй",
        )
    pos = position_for(ctx.positions, req.symbol)
    increases = increases_exposure(pos, req)
    return Check(
        rule="wind_down_direction",
        passed=not increases,
        limit_name="WIND_DOWN_DIRECTION",
        limit_value="reduce_only",
        actual_value="increase" if increases else "reduce",
        detail=(
            "winding_down үед зөвхөн позиц хаах / багасгах order зөвшөөрөгдөнө"
            if increases
            else "Позиц хаах чиглэл — winding_down үед ч зөвшөөрөгдөнө"
        ),
    )


def r3_restricted_symbol(ctx, req: OrderIntent) -> Check:
    restricted = req.symbol.upper() in ctx.limits.restricted_symbols
    return Check(
        rule="restricted_symbol",
        passed=not restricted,
        limit_name="RESTRICTED_SYMBOLS",
        limit_value=",".join(sorted(ctx.limits.restricted_symbols)) or "(хоосон)",
        actual_value=req.symbol.upper(),
    )


def r4_price_sanity(ctx, req: OrderIntent) -> Check:
    """Fat-finger хамгаалалт. Quote байхгүй бол УНАНА — мэдэхгүй нь зөвшөөрөл биш."""
    if ctx.quote is None:
        return Check(
            rule="price_sanity",
            passed=False,
            limit_name="PRICE_SANITY_PCT",
            limit_value=str(ctx.limits.price_sanity_pct),
            actual_value=None,
            detail="no_quote — лавлах үнэгүйгээр шалгах боломжгүй",
        )
    limit = ctx.limits.price_sanity_pct
    ref = ctx.quote.last
    worst = Decimal("0")
    for price in (req.limit_price, req.stop_price):
        if price is None:
            continue
        deviation = abs(price - ref) / ref * Decimal("100")
        worst = max(worst, deviation)
    return Check(
        rule="price_sanity",
        passed=worst <= limit,
        limit_name="PRICE_SANITY_PCT",
        limit_value=str(limit),
        actual_value=str(worst.quantize(Decimal("0.01"))),
    )


def r5_pdt_day_trades(ctx, req: OrderIntent) -> Check:
    under_floor = ctx.account.equity < PDT_EQUITY_FLOOR
    over_trades = ctx.day_trade_count > ctx.limits.max_day_trades
    return Check(
        rule="pdt_day_trades",
        passed=not (under_floor and over_trades),
        limit_name="MAX_DAY_TRADES",
        limit_value=str(ctx.limits.max_day_trades),
        actual_value=str(ctx.day_trade_count),
        detail=None if not under_floor else f"equity < {PDT_EQUITY_FLOOR} — PDT дүрэм идэвхтэй",
    )


def projected_value(existing_value: Decimal, notional: Decimal, increases: bool) -> Decimal:
    """Order-ийн ДАРААХ хүлээгдэж буй exposure (LLD §8.2).

    Багасгах order нь exposure-ыг НЭМЭХГҮЙ — эсрэг тохиолдолд том позицийг
    хаах бүр `position_pct`-д унаж, wind-down-ийн хаах зам боогдоно (AC-36).
    Эргүүлэлт нь `increases_exposure` дээр `True` тул энд НЭМЭГДЭНЭ: үр дүнг
    хэтрүүлэн үнэлэх нь татгалзал руу хазайна, зөвшөөрөл руу биш.
    """
    if increases:
        return existing_value + notional
    return max(Decimal("0"), existing_value - notional)


def r6_position_pct(ctx, req: OrderIntent) -> Check:
    price = reference_price(ctx, req)
    if price is None:
        return Check(
            rule="position_pct",
            passed=False,
            limit_name="MAX_POSITION_PCT",
            limit_value=str(ctx.limits.max_position_pct),
            detail="no_quote — позицийн хувийг тооцох боломжгүй",
        )
    existing = position_for(ctx.positions, req.symbol)
    existing_value = abs(existing.market_value) if existing else Decimal("0")
    projected = projected_value(
        existing_value, req.qty * price, increases_exposure(existing, req)
    )
    allowed = ctx.account.equity * ctx.limits.max_position_pct / Decimal("100")
    return Check(
        rule="position_pct",
        passed=projected <= allowed,
        limit_name="MAX_POSITION_PCT",
        limit_value=str(ctx.limits.max_position_pct),
        actual_value=money_str(projected / ctx.account.equity * Decimal("100")),
    )


def r7_total_exposure_pct(ctx, req: OrderIntent) -> Check:
    price = reference_price(ctx, req)
    if price is None:
        return Check(
            rule="total_exposure_pct",
            passed=False,
            limit_name="MAX_TOTAL_EXPOSURE_PCT",
            limit_value=str(ctx.limits.max_total_exposure_pct),
            detail="no_quote — нийт exposure-ийг тооцох боломжгүй",
        )
    exposure = projected_value(
        sum((abs(p.market_value) for p in ctx.positions), Decimal("0")),
        req.qty * price,
        increases_exposure(position_for(ctx.positions, req.symbol), req),
    )
    allowed = ctx.account.equity * ctx.limits.max_total_exposure_pct / Decimal("100")
    return Check(
        rule="total_exposure_pct",
        passed=exposure <= allowed,
        limit_name="MAX_TOTAL_EXPOSURE_PCT",
        limit_value=str(ctx.limits.max_total_exposure_pct),
        actual_value=money_str(exposure / ctx.account.equity * Decimal("100")),
    )


def r8_daily_loss_limit(ctx, req: OrderIntent) -> Check:
    """Өдрийн P&L = equity − өдрийн нээлтийн equity. Alpaca-ийн `last_equity`."""
    if ctx.account.last_equity is None:
        return Check(
            rule="daily_loss_limit",
            passed=True,
            limit_name="DAILY_LOSS_LIMIT",
            limit_value=money_str(ctx.limits.daily_loss_limit),
            detail="last_equity байхгүй — өдрийн P&L тооцоологдохгүй",
        )
    pnl = ctx.account.equity - ctx.account.last_equity
    return Check(
        rule="daily_loss_limit",
        passed=pnl > ctx.limits.daily_loss_limit,
        limit_name="DAILY_LOSS_LIMIT",
        limit_value=money_str(ctx.limits.daily_loss_limit),
        actual_value=money_str(pnl),
    )


def r9_order_notional(ctx, req: OrderIntent) -> Check:
    """Хэтэрвэл **ESCALATE_TO_HUMAN** — REJECT БИШ (LLD §8.1)."""
    price = reference_price(ctx, req)
    if price is None:
        return Check(
            rule="order_notional",
            passed=False,
            limit_name="MAX_ORDER_NOTIONAL",
            limit_value=money_str(ctx.limits.max_order_notional),
            detail="no_quote — notional тооцох боломжгүй",
        )
    notional = req.qty * price
    return Check(
        rule="order_notional",
        passed=notional <= ctx.limits.max_order_notional,
        limit_name="MAX_ORDER_NOTIONAL",
        limit_value=money_str(ctx.limits.max_order_notional),
        actual_value=money_str(notional),
    )


#: R1…R8 нь унавал REJECT. R9 нь тусдаа — ESCALATE.
REJECTING_RULES = (
    r1_system_state,
    r2_wind_down_direction,
    r3_restricted_symbol,
    r4_price_sanity,
    r5_pdt_day_trades,
    r6_position_pct,
    r7_total_exposure_pct,
    r8_daily_loss_limit,
)

ESCALATING_RULES = (r9_order_notional,)
