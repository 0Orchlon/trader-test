"""T-09 (ID=636) WS ingestion + staleness · T-10 (ID=637) EOD reconciliation.

DoD-ийн голууд:
- WS-ийг албадан салгавал босго хугацаанд `stale` төлөв `system` сувгаар
  гарна; дахин мессеж ирэхэд `stream_live`.
- Салсан үед хуучин өгөгдөл `stale` шошгогүйгээр тархахгүй.
- Reconcile: зөрүү үүсгэвэл audit мөр + тоолуур; зөрүү 0 бол аль нь ч биш.
- Зөрүүг ЛОКАЛ тооцооллоор биш, Alpaca-ийн утгаар засна.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import models
from app.broker.models import OrderSide, OrderStatus, OrderType, TimeInForce, TradeUpdate
from app.broker.reconcile import _compare, reconcile
from app.stream.bus import CHANNEL_ORDERS, CHANNEL_SYSTEM, EventBus
from app.stream.ingest import (
    BACKOFF_MAX_SECONDS,
    StalenessMonitor,
    TradeUpdateIngestor,
    backoff_delay,
)
from app.util.time import now_utc
from tests.fakes import broker_order


def update(client_order_id: str, *, status=OrderStatus.FILLED, event="fill", ts=None, **kw):
    return TradeUpdate(
        event=event,
        broker_order_id=kw.get("broker_order_id", "brk-agent"),
        client_order_id=client_order_id,
        status=status,
        filled_qty=kw.get("filled_qty", Decimal("10")),
        filled_avg_price=kw.get("filled_avg_price", Decimal("221.50")),
        ts=ts or now_utc(),
        raw=kw.get("raw", {"execution_id": "exec-1"}),
    )


async def drain(stream):
    for item in stream:
        yield item


# --- staleness ---


async def test_silence_past_the_threshold_publishes_stale(bus):
    monitor = StalenessMonitor(bus, stale_after_seconds=5)
    sub = bus.subscribe([CHANNEL_SYSTEM])
    start = now_utc()
    monitor.touch(CHANNEL_ORDERS, at=start)
    await monitor.sweep(at=start)  # шинэлэг — `stream_live`
    assert [m.payload["event"] for m in sub.drain()] == ["stream_live"]

    changed = await monitor.sweep(at=start + timedelta(seconds=6))
    assert changed == [(CHANNEL_ORDERS, True)]
    message = sub.drain()[0].payload
    assert message["event"] == "stream_stale"
    assert message["stale"] is True
    assert message["channel"] == CHANNEL_ORDERS
    assert message["last_update_at"].endswith("Z")


async def test_an_untouched_channel_starts_stale(bus):
    """«Би юу ч аваагүй тул бүх юм хэвийн» гэсэн таамаг БАЙХГҮЙ."""
    monitor = StalenessMonitor(bus, stale_after_seconds=5)
    assert monitor.track(CHANNEL_ORDERS).stale is True


async def test_reconnect_marks_the_channel_live_again(bus):
    monitor = StalenessMonitor(bus, stale_after_seconds=5)
    sub = bus.subscribe([CHANNEL_SYSTEM])
    start = now_utc()
    monitor.touch(CHANNEL_ORDERS, at=start)
    await monitor.sweep(at=start)
    await monitor.sweep(at=start + timedelta(seconds=6))
    sub.drain()

    monitor.touch(CHANNEL_ORDERS, at=start + timedelta(seconds=7))
    assert await monitor.sweep(at=start + timedelta(seconds=7)) == [(CHANNEL_ORDERS, False)]
    assert sub.drain()[0].payload["event"] == "stream_live"


async def test_stale_transition_is_published_once(bus):
    monitor = StalenessMonitor(bus, stale_after_seconds=5)
    sub = bus.subscribe([CHANNEL_SYSTEM])
    start = now_utc()
    monitor.touch(CHANNEL_ORDERS, at=start)
    await monitor.sweep(at=start)
    sub.drain()
    await monitor.sweep(at=start + timedelta(seconds=6))
    await monitor.sweep(at=start + timedelta(seconds=7))
    # Banner анивчихгүй — шилжилт нэг л удаа.
    assert [m.payload["event"] for m in sub.drain()] == ["stream_stale"]


def test_backoff_grows_and_is_capped():
    assert backoff_delay(0) < backoff_delay(1) < backoff_delay(2)
    assert backoff_delay(99) == BACKOFF_MAX_SECONDS


# --- trade-update ingestion ---


@pytest.fixture
def ingestor(engine, bus, broker):
    from app.db import make_sessionmaker

    monitor = StalenessMonitor(bus, stale_after_seconds=5)
    return TradeUpdateIngestor(make_sessionmaker(engine), broker, bus, monitor)


async def test_fill_updates_the_local_order_and_records_a_fill(ingestor, db_session, seeded_orders):
    order = [o for o in seeded_orders if o.client_order_id == "p3-seed-manual"][0]
    await ingestor.consume(drain([update("p3-seed-manual", filled_qty=Decimal("12"))]))
    await db_session.refresh(order)
    assert order.status == "filled"
    assert order.filled_qty == Decimal("12")
    assert order.filled_at is not None
    fills = (await db_session.execute(select(models.Fill))).scalars().all()
    assert len(fills) == 1
    assert fills[0].price == Decimal("221.50")
    # AC-1: Alpaca-ийн raw payload үлдэнэ, дахин тооцоолол БАЙХГҮЙ.
    assert fills[0].raw == {"execution_id": "exec-1"}


async def test_the_same_fill_event_twice_creates_one_fill(ingestor, db_session, seeded_orders):
    """Дахин холбогдоход ижил үйл явдал давтагдана — давхар fill болохгүй."""
    await ingestor.consume(drain([update("p3-seed-manual"), update("p3-seed-manual")]))
    count = (await db_session.execute(select(func.count(models.Fill.id)))).scalar_one()
    assert count == 1


async def test_an_unknown_client_order_id_creates_no_row(ingestor, db_session, bus):
    """Alpaca UI-аас нээсэн order — локал мөр ЗОХИОХГҮЙ (LLD §11.1)."""
    sub = bus.subscribe([CHANNEL_ORDERS])
    await ingestor.consume(drain([update("not-ours")]))
    count = (await db_session.execute(select(func.count(models.Order.id)))).scalar_one()
    assert count == 0
    assert sub.drain()[0].payload["known_locally"] is False


async def test_a_reject_records_a_breaker_event(ingestor, db_session, seeded_orders):
    await ingestor.consume(
        drain([update("p3-seed-manual", status=OrderStatus.REJECTED, event="rejected")])
    )
    rows = (
        await db_session.execute(
            select(models.BreakerEvent).where(models.BreakerEvent.kind == "order_reject")
        )
    ).scalars().all()
    assert [r.ok for r in rows] == [False]


async def test_a_dropped_stream_records_a_ws_disconnect(ingestor, db_session, broker):
    async def exploding():
        raise ConnectionResetError("WS салав")
        yield  # pragma: no cover

    broker.stream_trade_updates = exploding
    await ingestor.run_forever(max_cycles=1)
    rows = (
        await db_session.execute(
            select(models.BreakerEvent).where(models.BreakerEvent.kind == "ws_disconnect")
        )
    ).scalars().all()
    assert [r.ok for r in rows] == [False]


async def test_a_dropped_stream_publishes_stale_not_stale_data(ingestor, bus, broker):
    """Салсан үед хуучин өгөгдөл `stale` шошгогүйгээр тархахгүй (T-09 DoD в)."""
    sub = bus.subscribe([CHANNEL_SYSTEM])

    async def exploding():
        raise ConnectionResetError("WS салав")
        yield  # pragma: no cover

    broker.stream_trade_updates = exploding
    ingestor.monitor.track(CHANNEL_ORDERS).stale = False
    await ingestor.run_forever(max_cycles=1)
    events = [m.payload["event"] for m in sub.drain()]
    assert "stream_stale" in events


# --- reconciliation ---


def test_compare_finds_nothing_when_both_sides_agree(seeded_orders):
    remote = broker_order("p3-seed-manual", symbol="MSFT")
    local = [o for o in seeded_orders if o.client_order_id == "p3-seed-manual"]
    local[0].filled_qty = remote.filled_qty
    assert _compare(local, [remote]) == []


async def test_reconcile_with_no_drift_writes_nothing(db_session, broker, settings, seeded_orders):
    remote = broker_order("p3-seed-manual", symbol="MSFT")
    broker.open_orders = [remote]
    local = [o for o in seeded_orders if o.client_order_id == "p3-seed-manual"][0]
    local.filled_qty = remote.filled_qty
    await db_session.commit()

    report = await reconcile(db_session, broker, settings=settings)
    assert report.count == 0
    audits = (
        await db_session.execute(
            select(func.count(models.AuditLog.seq)).where(
                models.AuditLog.event_type == "reconciliation_drift"
            )
        )
    ).scalar_one()
    assert audits == 0


async def test_reconcile_adopts_the_broker_status(db_session, broker, settings, seeded_orders):
    """Alpaca нь эх сурвалж — локал тооцооллоор «засахгүй»."""
    from dataclasses import replace

    remote = replace(
        broker_order("p3-seed-manual", symbol="MSFT"),
        status=OrderStatus.FILLED,
        filled_qty=Decimal("12"),
    )
    broker.open_orders = [remote]
    local = [o for o in seeded_orders if o.client_order_id == "p3-seed-manual"][0]

    report = await reconcile(db_session, broker, settings=settings)
    assert report.count == 1
    assert report.drifts[0].kind == "status_mismatch"
    await db_session.refresh(local)
    assert local.status == "filled"
    assert local.filled_qty == Decimal("12")


async def test_reconcile_logs_every_drift(db_session, broker, settings, seeded_orders):
    broker.open_orders = []
    report = await reconcile(db_session, broker, settings=settings)
    assert report.count == 1 and report.drifts[0].kind == "missing_at_broker"
    row = (
        await db_session.execute(
            select(models.AuditLog).where(
                models.AuditLog.event_type == "reconciliation_drift"
            )
        )
    ).scalars().one()
    assert row.payload["drift_count"] == 1


async def test_an_order_unknown_locally_is_a_drift(db_session, broker, settings):
    broker.open_orders = [broker_order("p3-someone-elses")]
    report = await reconcile(db_session, broker, settings=settings)
    assert [d.kind for d in report.drifts] == ["unknown_locally"]


async def test_drift_above_the_limit_trips_the_breaker(db_session, broker, settings):
    """`RECONCILE_DRIFT_LIMIT` = 2 (тестийн орчин) — гурав нь халина."""
    from app.broker.models import SystemState
    from app.system.state import StateMachine

    machine = StateMachine(db_session, wind_down_grace=settings.WIND_DOWN_GRACE)
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="тест")

    broker.open_orders = [broker_order(f"p3-ghost-{i}") for i in range(3)]
    report = await reconcile(db_session, broker, settings=settings)
    assert report.count == 3
    assert report.breaker_tripped is True
    assert (await machine.current()).state is SystemState.HALTED


async def test_the_real_adapter_stream_runs_a_clean_cycle_without_a_disconnect(
    engine, bus, db_session, seeded_orders
):
    """UAT 5-р тойргийн блоклогчийн регресс.

    `AlpacaAdapter.stream_trade_updates()` нь `NotImplementedError` гаргадаг
    байсан тул мөчлөг БҮР `ws_disconnect` бичдэг байв — тоолуур босгыг
    давж, `POST /system/activate` мөнхөд 409. Бодит WS-ийн нэг цэвэр
    мөчлөг нь тоолуурыг ХӨДӨЛГӨХГҮЙ, харин fill-ийг шингээнэ.
    """
    import json

    from app.broker.alpaca import AlpacaAdapter
    from app.config.mode import TradingMode
    from app.db import make_sessionmaker
    from tests.fakes import fake_ws_connect
    from tests.unit.test_alpaca_stream import AUTH_OK, FILL, LISTENING

    _, connect = fake_ws_connect(
        [json.dumps(AUTH_OK), json.dumps(LISTENING), json.dumps(FILL).encode()]
    )
    adapter = AlpacaAdapter(
        mode=TradingMode.PAPER, api_key="k", api_secret="s", ws_connect=connect
    )
    monitor = StalenessMonitor(bus, stale_after_seconds=5)
    ingestor = TradeUpdateIngestor(make_sessionmaker(engine), adapter, bus, monitor)

    await ingestor.run_forever(max_cycles=1)

    disconnects = (
        await db_session.execute(
            select(models.BreakerEvent).where(models.BreakerEvent.kind == "ws_disconnect")
        )
    ).scalars().all()
    assert disconnects == [], "цэвэр мөчлөг нь `ws_disconnect` бичих ёсгүй"
    order = [o for o in seeded_orders if o.client_order_id == "p3-seed-manual"][0]
    await db_session.refresh(order)
    assert order.status == "filled"
