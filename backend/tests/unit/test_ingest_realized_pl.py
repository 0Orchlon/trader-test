"""Биелэлт ирэхэд realized P/L нь бодит үнээр бичигдэнэ."""
from __future__ import annotations

from decimal import Decimal

from app import models
from app.broker.models import OrderStatus, TradeUpdate
from app.stream.ingest import TradeUpdateIngestor
from app.util.time import now_utc


async def test_a_sell_fill_writes_realized_pl(db_session):
    row = models.Order(
        client_order_id="p3-exit-1",
        symbol="AAPL",
        side="sell",
        qty=Decimal("2"),
        order_type="market",
        time_in_force="day",
        status="accepted",
        origin="research_agent",
        risk_evaluation={"decision": "APPROVE"},
        mode="paper",
        submitted_at=now_utc(),
        entry_price=Decimal("100"),
    )
    db_session.add(row)
    await db_session.commit()

    # `apply` нь зөвхөн session-ыг хэрэглэнэ — бусад хамаарал энэ замд орохгүй.
    ingestor = TradeUpdateIngestor(None, None, None, None)
    await ingestor.apply(
        db_session,
        TradeUpdate(
            event="fill",
            broker_order_id="brk-exit-1",
            client_order_id="p3-exit-1",
            status=OrderStatus.FILLED,
            filled_qty=Decimal("2"),
            filled_avg_price=Decimal("110"),
            ts=now_utc(),
            raw={"execution_id": "exec-exit-1"},
        ),
    )

    assert row.realized_pl == Decimal("20")


async def test_a_partially_filled_cancel_still_writes_realized_pl(db_session):
    """Нимгэн ликвидтэй үед stop-loss хэсэгчлэн биелээд цуцлагддаг. Биелсэн
    ширхэг нь БОДИТ алдагдал — үүнийг бичихгүй бол ledger зөвхөн ялалт цуглуулна."""
    row = models.Order(
        client_order_id="p3-exit-2",
        symbol="AAPL",
        side="sell",
        qty=Decimal("10"),
        order_type="market",
        time_in_force="day",
        status="accepted",
        origin="research_agent",
        risk_evaluation={"decision": "APPROVE"},
        mode="paper",
        submitted_at=now_utc(),
        entry_price=Decimal("100"),
    )
    db_session.add(row)
    await db_session.commit()

    ingestor = TradeUpdateIngestor(None, None, None, None)
    await ingestor.apply(
        db_session,
        TradeUpdate(
            event="canceled",
            broker_order_id="brk-exit-2",
            client_order_id="p3-exit-2",
            status=OrderStatus.CANCELED,
            filled_qty=Decimal("3"),
            filled_avg_price=Decimal("90"),
            ts=now_utc(),
            raw={},
        ),
    )

    assert row.realized_pl == Decimal("-30")


async def test_a_cancel_with_no_fill_leaves_realized_pl_null(db_session):
    row = models.Order(
        client_order_id="p3-exit-3",
        symbol="AAPL",
        side="sell",
        qty=Decimal("10"),
        order_type="market",
        time_in_force="day",
        status="accepted",
        origin="research_agent",
        risk_evaluation={"decision": "APPROVE"},
        mode="paper",
        submitted_at=now_utc(),
        entry_price=Decimal("100"),
    )
    db_session.add(row)
    await db_session.commit()

    ingestor = TradeUpdateIngestor(None, None, None, None)
    await ingestor.apply(
        db_session,
        TradeUpdate(
            event="canceled",
            broker_order_id="brk-exit-3",
            client_order_id="p3-exit-3",
            status=OrderStatus.CANCELED,
            filled_qty=Decimal("0"),
            filled_avg_price=None,
            ts=now_utc(),
            raw={},
        ),
    )

    assert row.realized_pl is None
