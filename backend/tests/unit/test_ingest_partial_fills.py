"""Хэсэгчилсэн биелэлт бүр ӨӨРИЙН тоо/үнээр бичигдэнэ (нийлбэрээр биш)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app import models
from app.broker.alpaca import AlpacaAdapter
from app.stream.ingest import TradeUpdateIngestor
from app.util.time import now_utc


def _payload(qty: str, price: str, cum_qty: str, avg: str, exec_id: str) -> dict:
    return {
        "event": "partial_fill",
        "timestamp": now_utc().isoformat(),
        "execution_id": exec_id,
        "qty": qty,
        "price": price,
        "order": {
            "id": "brk-pf-1",
            "client_order_id": "p3-pf-1",
            "status": "partially_filled",
            "filled_qty": cum_qty,
            "filled_avg_price": avg,
        },
    }


async def test_partial_fills_record_per_execution_qty(db_session):
    row = models.Order(
        client_order_id="p3-pf-1",
        symbol="AAPL",
        side="buy",
        qty=Decimal("10"),
        order_type="market",
        time_in_force="day",
        status="accepted",
        origin="research_agent",
        risk_evaluation={"decision": "APPROVE"},
        mode="paper",
        submitted_at=now_utc(),
    )
    db_session.add(row)
    await db_session.commit()

    mapper = AlpacaAdapter.map_trade_update
    ingestor = TradeUpdateIngestor(None, None, None, None)
    for raw in (
        _payload("3", "100", "3", "100", "exec-1"),
        _payload("7", "110", "10", "107", "exec-2"),
    ):
        await ingestor.apply(db_session, mapper(None, raw))

    fills = (
        (await db_session.execute(select(models.Fill).where(models.Fill.order_id == row.id)))
        .scalars()
        .all()
    )
    assert sum(f.qty for f in fills) == Decimal("10")
    assert sorted(f.price for f in fills) == [Decimal("100"), Decimal("110")]
