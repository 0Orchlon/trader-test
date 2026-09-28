"""Гар позицийг ашигтай болмогц авто-хаах toggle (T-99)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app import models
from app.broker.models import Position, PositionSide
from app.execution.manual_take_profit import get_enabled, run_manual_take_profit, set_enabled
from app.system.state import StateMachine, SystemState
from app.util.time import now_utc
from tests.fakes import broker_order, quote

NOW = now_utc()


def _position(symbol: str, qty: str, unrealized_pl: str, side: PositionSide = PositionSide.LONG) -> Position:
    return Position(
        symbol=symbol,
        qty=Decimal(qty),
        side=side,
        avg_entry_price=Decimal("100.00"),
        market_value=Decimal("1000.00"),
        unrealized_pl=Decimal(unrealized_pl),
    )


async def _seed(engine, settings, *, state: SystemState = SystemState.ACTIVE, enabled: bool = True):
    from app.db import make_sessionmaker

    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        machine = StateMachine(session, wind_down_grace=settings.WIND_DOWN_GRACE)
        await machine.ensure_initialised()
        await machine.transition(state, by="operator", reason="тест")
        await set_enabled(session, enabled)
    return sessionmaker


async def _add_filled_order(sessionmaker, symbol: str, origin: str, qty: str):
    async with sessionmaker() as session:
        session.add(
            models.Order(
                client_order_id=f"p3-entry-{symbol}-{origin}",
                symbol=symbol,
                side="buy",
                qty=Decimal(qty),
                filled_qty=Decimal(qty),
                order_type="market",
                time_in_force="gtc",
                status="filled",
                origin=origin,
                origin_detail=None,
                risk_evaluation={"decision": "APPROVE"},
                mode="paper",
                submitted_at=NOW,
                filled_at=NOW,
            )
        )
        await session.commit()


async def test_get_enabled_defaults_to_false(engine, settings):
    from app.db import make_sessionmaker

    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        from app.system.state import StateMachine as SM

        await SM(session, wind_down_grace=settings.WIND_DOWN_GRACE).ensure_initialised()
        assert await get_enabled(session) is False


async def test_set_enabled_persists(engine, settings):
    from app.db import make_sessionmaker

    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        from app.system.state import StateMachine as SM

        await SM(session, wind_down_grace=settings.WIND_DOWN_GRACE).ensure_initialised()
        assert await set_enabled(session, True) is True
    async with sessionmaker() as session:
        assert await get_enabled(session) is True
    async with sessionmaker() as session:
        assert await set_enabled(session, False) is False
    async with sessionmaker() as session:
        assert await get_enabled(session) is False


async def test_a_profitable_external_position_is_closed(engine, settings, broker):
    sessionmaker = await _seed(engine, settings)
    broker.positions = [_position("BTCUSD", "1", "5.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90000.00")}
    await run_manual_take_profit(sessionmaker, settings, broker, None)

    assert [(o.symbol, o.side.value, str(o.qty)) for o in broker.submitted] == [
        ("BTC/USD", "sell", "1")
    ]


async def test_disabled_toggle_does_nothing(engine, settings, broker):
    sessionmaker = await _seed(engine, settings, enabled=False)
    broker.positions = [_position("BTCUSD", "1", "5.00")]
    await run_manual_take_profit(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_a_losing_position_is_not_touched(engine, settings, broker):
    sessionmaker = await _seed(engine, settings)
    broker.positions = [_position("BTCUSD", "1", "-5.00")]
    await run_manual_take_profit(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_a_pure_research_agent_position_is_left_to_exits_py(engine, settings, broker):
    sessionmaker = await _seed(engine, settings)
    await _add_filled_order(sessionmaker, "BTC/USD", "research_agent", "1")
    broker.positions = [_position("BTCUSD", "1", "5.00")]
    await run_manual_take_profit(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_a_mixed_origin_profitable_position_is_still_closed(engine, settings, broker):
    """Холимог гарал (operator + research_agent хоёул) — exits.py-ийн
    `agent_qty` шалгуурыг (others_flat) хангахгүй тул тэндээс хаагдахгүй,
    иймд энд удирдана."""
    sessionmaker = await _seed(engine, settings)
    await _add_filled_order(sessionmaker, "BTC/USD", "research_agent", "1")
    await _add_filled_order(sessionmaker, "BTC/USD", "manual_operator", "1")
    broker.positions = [_position("BTCUSD", "2", "5.00")]
    await run_manual_take_profit(sessionmaker, settings, broker, None)

    assert [o.qty for o in broker.submitted] == [Decimal("2")]


async def test_halted_state_blocks_everything(engine, settings, broker):
    sessionmaker = await _seed(engine, settings, state=SystemState.HALTED)
    broker.positions = [_position("BTCUSD", "1", "5.00")]
    await run_manual_take_profit(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_an_open_broker_order_blocks_a_duplicate_submit(engine, settings, broker):
    sessionmaker = await _seed(engine, settings)
    broker.positions = [_position("BTCUSD", "1", "5.00")]
    broker.open_orders = [broker_order("external-open-order", symbol="BTC/USD")]
    await run_manual_take_profit(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_a_short_position_covers_by_buying(engine, settings, broker):
    sessionmaker = await _seed(engine, settings)
    broker.positions = [_position("BTCUSD", "1", "5.00", side=PositionSide.SHORT)]
    await run_manual_take_profit(sessionmaker, settings, broker, None)

    assert [o.side.value for o in broker.submitted] == ["buy"]


async def test_a_symbol_outside_the_watchlist_is_never_closed(engine, settings, broker):
    """`BTCUSD` -> `BTC/USD` буулгах боломжгүй symbol-ыг ХӨНДӨХГҮЙ."""
    sessionmaker = await _seed(engine, settings)
    broker.positions = [_position("ZZZUSD", "1", "5.00")]
    await run_manual_take_profit(sessionmaker, settings, broker, None)

    assert broker.submitted == []
