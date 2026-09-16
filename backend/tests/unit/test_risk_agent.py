"""T-11 (ID=638) — Risk Agent, детерминистик хаалга (FR-3, AC-3, AC-4).

LLD §8.1-ийн дүрмийн хүснэгтийг мөр мөрөөр. `evaluate()` нь ЦЭВЭР ФУНКЦ —
энэ файлд DB, сүлжээ, цаг унших дуудалт БАЙХГҮЙ.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

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
    ValidatedOrder,
)
from app.risk.agent import RiskContext, evaluate
from app.risk.limits import RiskLimits
from app.util.time import parse_iso

NOW = parse_iso("2026-09-16T14:30:00Z")

LIMITS = RiskLimits(
    max_order_notional=Decimal("5000.00"),
    max_position_pct=Decimal("10"),
    max_total_exposure_pct=Decimal("60"),
    daily_loss_limit=Decimal("-2000.00"),
    max_day_trades=3,
    price_sanity_pct=Decimal("10"),
    restricted_symbols=frozenset({"GME"}),
)

ACCOUNT = Account(
    account_id="PA1",
    equity=Decimal("100000.00"),
    cash=Decimal("50000.00"),
    buying_power=Decimal("90000.00"),
    last_equity=Decimal("100200.00"),
    pattern_day_trader=False,
    day_trade_count=0,
)

QUOTE = Quote(
    symbol="AAPL",
    bid=Decimal("220.00"),
    ask=Decimal("220.20"),
    last=Decimal("220.10"),
    quote_ts=NOW,
)


def ctx(**kw) -> RiskContext:
    base = dict(
        account=ACCOUNT,
        positions=[],
        quote=QUOTE,
        day_trade_count=0,
        system_state=SystemState.ACTIVE,
        limits=LIMITS,
        now=NOW,
    )
    base.update(kw)
    return RiskContext(**base)


def intent(**kw) -> OrderIntent:
    base = dict(
        symbol="AAPL",
        side=OrderSide.BUY,
        qty=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        limit_price=None,
        stop_price=None,
    )
    base.update(kw)
    return OrderIntent(**base)


def pos(symbol="AAPL", qty="40", side=PositionSide.LONG, market_value="8000.00") -> Position:
    return Position(
        symbol=symbol,
        qty=Decimal(qty),
        side=side,
        avg_entry_price=Decimal("200.00"),
        market_value=Decimal(market_value),
        unrealized_pl=Decimal("0.00"),
    )


# --- нэгтгэх дүрэм ---


def test_clean_order_is_approved_and_yields_validated_order():
    result = evaluate(ctx(), intent())
    assert result.decision is RiskDecision.APPROVE
    assert isinstance(result.validated_order, ValidatedOrder)
    assert result.validated_order.qty == Decimal("10")


def test_every_rule_runs_even_after_first_failure():
    """LLD §8.1 — operator юу унасныг БҮХЭЛД нь харна."""
    result = evaluate(ctx(system_state=SystemState.HALTED), intent(symbol="GME"))
    rules = {c.rule for c in result.checks}
    assert rules == {
        "system_state",
        "wind_down_direction",
        "restricted_symbol",
        "price_sanity",
        "pdt_day_trades",
        "position_pct",
        "total_exposure_pct",
        "daily_loss_limit",
        "order_notional",
    }


def test_reject_beats_escalate():
    """Хоёул унавал REJECT (LLD §8.1)."""
    result = evaluate(
        ctx(system_state=SystemState.HALTED), intent(qty=Decimal("1000"))  # notional > 5000
    )
    assert result.decision is RiskDecision.REJECT
    assert result.validated_order is None


# --- R1 system_state ---


def test_r1_halted_rejects():
    result = evaluate(ctx(system_state=SystemState.HALTED), intent())
    assert result.decision is RiskDecision.REJECT
    assert result.reason and "halted" in result.reason


# --- R2 wind_down_direction ---


@pytest.mark.parametrize(
    "position,order,expected_pass",
    [
        (None, dict(side=OrderSide.BUY), False),  # шинэ symbol = нэмэгдүүлэлт
        (pos(), dict(side=OrderSide.BUY), False),  # нэмж авах
        (pos(), dict(side=OrderSide.SELL, qty=Decimal("40")), True),  # бүрэн хаалт
        (pos(), dict(side=OrderSide.SELL, qty=Decimal("10")), True),  # хэсэгчилсэн хаалт
        (pos(), dict(side=OrderSide.SELL, qty=Decimal("60")), False),  # эргүүлэлт
        (
            pos(side=PositionSide.SHORT, qty="-40"),
            dict(side=OrderSide.SELL),
            False,
        ),  # нэмж богиносгох
        (
            pos(side=PositionSide.SHORT, qty="-40"),
            dict(side=OrderSide.BUY, qty=Decimal("40")),
            True,
        ),  # short хаах
    ],
)
def test_r2_wind_down_direction(position, order, expected_pass):
    positions = [position] if position else []
    result = evaluate(
        ctx(system_state=SystemState.WINDING_DOWN, positions=positions), intent(**order)
    )
    check = next(c for c in result.checks if c.rule == "wind_down_direction")
    assert check.passed is expected_pass
    if not expected_pass:
        assert result.decision is RiskDecision.REJECT


def test_r2_does_not_apply_when_active():
    result = evaluate(ctx(), intent())
    check = next(c for c in result.checks if c.rule == "wind_down_direction")
    assert check.passed is True


def test_wind_down_adds_rules_never_removes_them():
    """LLD §8.2 — хаах order-т ч R3…R9 бүрэн ажиллана."""
    result = evaluate(
        ctx(system_state=SystemState.WINDING_DOWN, positions=[pos(symbol="GME")]),
        intent(symbol="GME", side=OrderSide.SELL, qty=Decimal("40")),
    )
    restricted = next(c for c in result.checks if c.rule == "restricted_symbol")
    assert restricted.passed is False
    assert result.decision is RiskDecision.REJECT


# --- R3…R9 ---


def test_r3_restricted_symbol():
    result = evaluate(ctx(), intent(symbol="GME"))
    assert result.decision is RiskDecision.REJECT


def test_r4_price_sanity_fat_finger():
    result = evaluate(
        ctx(), intent(order_type=OrderType.LIMIT, limit_price=Decimal("2200.00"))
    )
    check = next(c for c in result.checks if c.rule == "price_sanity")
    assert check.passed is False
    assert result.decision is RiskDecision.REJECT


def test_r4_no_quote_is_a_rejection_not_a_pass():
    """LLD §8.3 — мэдэхгүй байдал нь зөвшөөрөл БИШ."""
    result = evaluate(ctx(quote=None), intent())
    check = next(c for c in result.checks if c.rule == "price_sanity")
    assert check.passed is False
    assert result.reason and "no_quote" in result.reason


def test_r5_pdt_only_bites_under_25k():
    small = replace(ACCOUNT, equity=Decimal("20000.00"))
    over = evaluate(ctx(account=small, day_trade_count=4), intent())
    assert over.decision is RiskDecision.REJECT
    rich = evaluate(ctx(day_trade_count=4), intent())
    assert next(c for c in rich.checks if c.rule == "pdt_day_trades").passed is True


def test_r6_position_pct():
    # 10 000-аас дээш позиц = equity-ийн 10%-иас их.
    result = evaluate(ctx(), intent(qty=Decimal("50")))  # 50 × 220.10 = 11005.00
    assert next(c for c in result.checks if c.rule == "position_pct").passed is False


def test_r6_counts_existing_position_of_same_symbol():
    result = evaluate(
        ctx(positions=[pos(market_value="9000.00")]), intent(qty=Decimal("10"))
    )
    check = next(c for c in result.checks if c.rule == "position_pct")
    assert check.passed is False  # 9000 + 2201 = 11201 > 10 000


def test_r7_total_exposure_pct():
    heavy = [pos(symbol=f"S{i}", market_value="10000.00") for i in range(6)]
    result = evaluate(ctx(positions=heavy), intent(qty=Decimal("1")))
    assert next(c for c in result.checks if c.rule == "total_exposure_pct").passed is False


def test_r8_daily_loss_limit():
    losing = replace(
        ACCOUNT, equity=Decimal("97000.00"), last_equity=Decimal("100000.00")
    )
    result = evaluate(ctx(account=losing), intent())
    assert next(c for c in result.checks if c.rule == "daily_loss_limit").passed is False
    assert result.decision is RiskDecision.REJECT


def test_r9_notional_escalates_never_rejects():
    result = evaluate(ctx(), intent(qty=Decimal("30")))  # 30 × 220.10 = 6603.00
    assert result.decision is RiskDecision.ESCALATE_TO_HUMAN
    assert result.validated_order is None


def test_checks_carry_limit_names_and_values():
    result = evaluate(ctx(), intent(qty=Decimal("30")))
    check = next(c for c in result.checks if c.rule == "order_notional")
    assert check.limit_name == "MAX_ORDER_NOTIONAL"
    assert check.limit_value == "5000.00"
    assert check.actual_value == "6603.00"


def test_evaluate_is_pure_same_input_same_output():
    a = evaluate(ctx(), intent())
    b = evaluate(ctx(), intent())
    assert a.decision == b.decision
    assert [c.rule for c in a.checks] == [c.rule for c in b.checks]
    assert a.validated_order.client_order_id == b.validated_order.client_order_id


# --- T-45 (ID=670) · wind-down чиглэлийн дүрэм, ил нэрлэсэн кейсүүд (AC-35) ---
#
# Property тест (tests/property) нь «нэмэгдүүлэх нь ХЭЗЭЭ Ч APPROVE болохгүй»
# гэдгийг 10 000 кейсээр барина. Эдгээр нь DoD-ийн нөгөө гурван тал: хаах
# order ДАМЖИНА, эргүүлэх order ТАТГАЛЗАНА, хязгаар СУЛРАХГҮЙ.


def test_wind_down_lets_a_closing_order_through():
    result = evaluate(
        ctx(system_state=SystemState.WINDING_DOWN, positions=[pos(qty="20", market_value="4000.00")]),
        intent(side=OrderSide.SELL, qty=Decimal("20")),
    )
    assert result.decision is RiskDecision.APPROVE
    assert result.validated_order is not None


def test_wind_down_lets_a_partial_close_through():
    result = evaluate(
        ctx(system_state=SystemState.WINDING_DOWN, positions=[pos(qty="40")]),
        intent(side=OrderSide.SELL, qty=Decimal("10")),
    )
    assert result.decision is RiskDecision.APPROVE


def test_wind_down_rejects_a_reversal():
    """Хаагаад эсрэг тийш нээх нь ШИНЭ эрсдэл — хэсэгчилсэн хаалт биш."""
    result = evaluate(
        ctx(system_state=SystemState.WINDING_DOWN, positions=[pos(qty="40")]),
        intent(side=OrderSide.SELL, qty=Decimal("60")),
    )
    assert result.decision is RiskDecision.REJECT
    assert "wind_down_direction" in result.reason


def test_wind_down_rejects_a_brand_new_symbol():
    result = evaluate(
        ctx(system_state=SystemState.WINDING_DOWN, positions=[]),
        intent(symbol="NVDA", side=OrderSide.BUY),
    )
    assert result.decision is RiskDecision.REJECT


def test_wind_down_rejects_adding_to_a_short():
    result = evaluate(
        ctx(
            system_state=SystemState.WINDING_DOWN,
            positions=[pos(qty="-40", side=PositionSide.SHORT)],
        ),
        intent(side=OrderSide.SELL, qty=Decimal("10")),
    )
    assert result.decision is RiskDecision.REJECT


def test_wind_down_does_not_relax_the_hard_limits():
    """AC-36 — хаах order ч §7-ийн хязгаарыг дайрна."""
    result = evaluate(
        ctx(
            system_state=SystemState.WINDING_DOWN,
            positions=[pos(symbol="GME", qty="40", market_value="800.00")],
        ),
        intent(symbol="GME", side=OrderSide.SELL, qty=Decimal("40")),
    )
    assert result.decision is RiskDecision.REJECT
    assert "restricted_symbol" in result.reason


def test_halted_beats_wind_down_direction():
    """`halted` үед хаах order ч дамжихгүй (AC-35)."""
    result = evaluate(
        ctx(system_state=SystemState.HALTED, positions=[pos(qty="40")]),
        intent(side=OrderSide.SELL, qty=Decimal("40")),
    )
    assert result.decision is RiskDecision.REJECT
