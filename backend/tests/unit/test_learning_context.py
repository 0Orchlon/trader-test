"""Prompt-д орох "сургалт" нь шатны нэр биш, МӨНГӨ байх ёстой."""
from __future__ import annotations

from decimal import Decimal

from app import models
from app.agents.runner import _learning_context, closed_trade_stats
from app.util.time import now_utc


def _closed(client_order_id: str, symbol: str, pl: str, detail: str) -> models.Order:
    return models.Order(
        client_order_id=client_order_id,
        symbol=symbol,
        side="sell",
        qty=Decimal("2"),
        order_type="market",
        time_in_force="day",
        status="filled",
        origin="research_agent",
        origin_detail=detail,
        risk_evaluation={"decision": "APPROVE"},
        mode="paper",
        submitted_at=now_utc(),
        filled_at=now_utc(),
        entry_price=Decimal("100"),
        realized_pl=Decimal(pl),
    )


async def test_a_loss_renders_its_dollars_and_exit_reason(db_session):
    db_session.add(_closed("p3-close-1", "AAPL", "-12.5", "exit:stop_loss"))
    await db_session.commit()

    text = await _learning_context(db_session)

    assert "-$12.50" in text
    assert "stop_loss" in text
    # Шатны нэр («executed») буцаж ирвэл энэ мөчлөг дахин худал сургана.
    assert "executed" not in text


async def test_per_symbol_aggregate_counts_wins_and_losses(db_session):
    db_session.add(_closed("p3-close-2", "AAPL", "-12.5", "exit:stop_loss"))
    db_session.add(_closed("p3-close-3", "AAPL", "30", "exit:take_profit"))
    await db_session.commit()

    stats = await closed_trade_stats(db_session)

    assert stats["per_symbol"] == [
        {"symbol": "AAPL", "trades": 2, "wins": 1, "losses": 1, "net": Decimal("17.5")}
    ]
    assert "AAPL: 2 trades, 1W/1L, net +$17.50" in await _learning_context(db_session)


async def test_one_symbol_spelled_two_ways_is_one_track_record(db_session):
    """`BTC/USD` ба `BTCUSD` хоёр тусдаа түүх болбол сургалт хуурамч болно."""
    db_session.add(_closed("p3-close-4", "BTC/USD", "-10", "exit:stop_loss"))
    db_session.add(_closed("p3-close-5", "BTCUSD", "25", "exit:take_profit"))
    await db_session.commit()

    stats = await closed_trade_stats(db_session)

    assert stats["per_symbol"] == [
        {"symbol": "BTC/USD", "trades": 2, "wins": 1, "losses": 1, "net": Decimal("15")}
    ]


async def test_unfilled_rows_do_not_crowd_out_real_closes(db_session):
    """`filled_at IS NULL` нь Postgres дээр DESC үед тэргүүнд гардаг — 20
    мөрийн цонхыг эзлэх ёсгүй."""
    for i in range(3):
        row = _closed(f"p3-null-{i}", "AAPL", "-1", "exit:stop_loss")
        row.filled_at = None
        db_session.add(row)
    db_session.add(_closed("p3-close-6", "AAPL", "42", "exit:take_profit"))
    await db_session.commit()

    recent = (await closed_trade_stats(db_session))["recent"]

    assert recent[0]["realized_pl"] == Decimal("42")


async def test_the_line_prints_the_filled_quantity_not_the_ordered_one(db_session):
    """`realized_pl`-ийг ingest нь `filled_qty`-гээс тооцдог — хажууд нь
    захиалсан `qty` хэвлэвэл мөр дээрх тоо ба мөнгө зөрнө."""
    row = _closed("p3-partial-1", "AAPL", "-5", "exit:stop_loss")
    row.qty = Decimal("10")
    row.filled_qty = Decimal("2")
    db_session.add(row)
    await db_session.commit()

    recent = (await closed_trade_stats(db_session))["recent"]

    assert recent[0]["qty"] == Decimal("2")


async def test_open_orders_are_not_closed_trades(db_session):
    row = _closed("p3-open-1", "AAPL", "0", "local/qwen3")
    row.realized_pl = None
    row.filled_at = None
    db_session.add(row)
    await db_session.commit()

    assert await closed_trade_stats(db_session) == {"per_symbol": [], "recent": []}
    assert "No closed trades yet" in await _learning_context(db_session)


async def test_rejected_proposals_are_the_one_surviving_stage_line(db_session):
    for i, outcome in enumerate(("grounding_failed", "risk_rejected", "executed")):
        db_session.add(
            models.AgentDecision(
                agent="research",
                provider="local",
                model="qwen3",
                session_id=f"s-{i}",
                proposal={"symbol": "AAPL", "side": "buy"},
                grounding={},
                outcome=outcome,
                created_at=now_utc(),
            )
        )
    await db_session.commit()

    text = await _learning_context(db_session)

    assert "2 of your last 3 proposals" in text
    assert "executed" not in text
