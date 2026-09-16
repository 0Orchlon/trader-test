"""T-12 (ID=639) — Risk Agent-ийн property-based тест (AC-4, AC-35).

`evaluate()` цэвэр функц тул 10 000 кейс DB-гүйгээр ажиллана. Энд шалгагдаж
буй зүйл нь тодорхой тоо биш, **үл хөдлөх дүрмүүд**.
"""
from __future__ import annotations

from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.broker.models import (
    Account,
    OrderIntent,
    OrderSide,
    OrderType,
    Position,
    PositionSide,
    Quote,
    RiskDecision,
    SystemState,
    TimeInForce,
)
from app.risk.agent import RiskContext, evaluate
from app.risk.limits import RiskLimits
from app.risk.rules import increases_exposure, position_for
from app.util.time import parse_iso

NOW = parse_iso("2026-09-16T14:30:00Z")

#: 8 property × 1300 = 10 400 кейс — LLD §18.1-ийн «≥10 000»-ийн хэмжигдсэн тал.
MANY = settings(
    max_examples=1300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

money = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2, allow_nan=False
)
qty = st.decimals(min_value=Decimal("0.001"), max_value=Decimal("10000"), places=3)


@st.composite
def limits(draw) -> RiskLimits:
    return RiskLimits(
        max_order_notional=draw(money),
        max_position_pct=draw(st.decimals(min_value=1, max_value=100, places=0)),
        max_total_exposure_pct=draw(st.decimals(min_value=1, max_value=100, places=0)),
        daily_loss_limit=draw(
            st.decimals(min_value=Decimal("-50000"), max_value=Decimal("-1"), places=2)
        ),
        max_day_trades=draw(st.integers(min_value=0, max_value=10)),
        price_sanity_pct=draw(st.decimals(min_value=1, max_value=50, places=0)),
        restricted_symbols=draw(
            st.frozensets(st.sampled_from(["GME", "AMC", "BBBY"]), max_size=3)
        ),
    )


@st.composite
def positions(draw) -> list[Position]:
    def one(symbol):
        side = draw(st.sampled_from(list(PositionSide)))
        amount = draw(qty)
        return Position(
            symbol=symbol,
            qty=amount if side is PositionSide.LONG else -amount,
            side=side,
            avg_entry_price=draw(money),
            market_value=draw(money),
            unrealized_pl=Decimal("0.00"),
        )

    symbols = draw(st.lists(st.sampled_from(["AAPL", "MSFT", "GME", "NVDA"]), unique=True, max_size=4))
    return [one(s) for s in symbols]


@st.composite
def contexts(draw, state=None) -> RiskContext:
    equity = draw(st.decimals(min_value=Decimal("1000"), max_value=Decimal("1000000"), places=2))
    has_quote = draw(st.booleans())
    last = draw(money)
    return RiskContext(
        account=Account(
            account_id="PA1",
            equity=equity,
            cash=equity / 2,
            buying_power=equity,
            last_equity=draw(st.one_of(st.none(), money)),
            pattern_day_trader=draw(st.booleans()),
            day_trade_count=draw(st.integers(min_value=0, max_value=10)),
        ),
        positions=draw(positions()),
        quote=(
            Quote(symbol="AAPL", bid=last, ask=last, last=last, quote_ts=NOW)
            if has_quote
            else None
        ),
        day_trade_count=draw(st.integers(min_value=0, max_value=10)),
        system_state=state or draw(st.sampled_from(list(SystemState))),
        limits=draw(limits()),
        now=NOW,
    )


@st.composite
def intents(draw) -> OrderIntent:
    order_type = draw(st.sampled_from(list(OrderType)))
    return OrderIntent(
        symbol=draw(st.sampled_from(["AAPL", "MSFT", "GME", "NVDA"])),
        side=draw(st.sampled_from(list(OrderSide))),
        qty=draw(qty),
        order_type=order_type,
        time_in_force=draw(st.sampled_from(list(TimeInForce))),
        limit_price=draw(st.one_of(st.none(), money)),
        stop_price=draw(st.one_of(st.none(), money)),
    )


@MANY
@given(ctx=contexts(), req=intents())
def test_halted_never_approves(ctx, req):
    """AC-3 — `halted` үед ямар ч оролтод APPROVE гарахгүй."""
    if ctx.system_state is not SystemState.HALTED:
        return
    result = evaluate(ctx, req)
    assert result.decision is RiskDecision.REJECT
    assert result.validated_order is None


@MANY
@given(ctx=contexts(state=SystemState.WINDING_DOWN), req=intents())
def test_winding_down_never_approves_exposure_increase(ctx, req):
    """AC-35 — чиглэлийн дүрэм."""
    result = evaluate(ctx, req)
    if increases_exposure(position_for(ctx.positions, req.symbol), req):
        assert result.decision is RiskDecision.REJECT


@MANY
@given(ctx=contexts(), req=intents())
def test_approve_implies_validated_order_matches_request(ctx, req):
    """Risk-ийн зөвшөөрснөөс ӨӨР зүйл илгээгдэх боломжгүй."""
    result = evaluate(ctx, req)
    if result.decision is not RiskDecision.APPROVE:
        assert result.validated_order is None
        return
    v = result.validated_order
    assert (v.symbol, v.side, v.qty, v.order_type) == (
        req.symbol,
        req.side,
        req.qty,
        req.order_type,
    )
    assert (v.limit_price, v.stop_price) == (req.limit_price, req.stop_price)


@MANY
@given(ctx=contexts(), req=intents())
def test_no_quote_never_approves(ctx, req):
    """LLD §8.3 — мэдэхгүй байдал нь зөвшөөрөл БИШ."""
    if ctx.quote is not None or req.limit_price is not None:
        return
    assert evaluate(ctx, req).decision is not RiskDecision.APPROVE


@MANY
@given(ctx=contexts(), req=intents())
def test_all_nine_rules_always_present(ctx, req):
    result = evaluate(ctx, req)
    assert len(result.checks) == 9
    assert len({c.rule for c in result.checks}) == 9


@MANY
@given(ctx=contexts(), req=intents())
def test_decision_is_deterministic(ctx, req):
    assert evaluate(ctx, req).decision is evaluate(ctx, req).decision


@MANY
@given(ctx=contexts(), req=intents())
def test_reject_dominates_escalate(ctx, req):
    result = evaluate(ctx, req)
    rejecting = [c for c in result.checks if not c.passed and c.rule != "order_notional"]
    if rejecting:
        assert result.decision is RiskDecision.REJECT


@MANY
@given(ctx=contexts(), req=intents())
def test_approve_implies_every_check_passed(ctx, req):
    result = evaluate(ctx, req)
    if result.decision is RiskDecision.APPROVE:
        assert all(c.passed for c in result.checks)
