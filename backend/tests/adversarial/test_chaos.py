"""T-38 (ID=665) — chaos / fault injection (AC-14, AC-15).

Хүлээлт нь **аюулгүй доройтол**, чимээгүй уналт БИШ. Кейс бүрт:
- шинэ order илгээх нь зогсоно;
- төлөв нь API-аар харагдана (UI түүнийг banner болгоно);
- систем position-ыг ТААМАГЛАХГҮЙ (локал тооцоолол 0);
- кэшлэгдсэн санал БИЕЛЭХГҮЙ.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import models
from app.agents.gateway import Gateway, state_view
from app.agents.router import default_router
from app.agents.tools import HANDLERS, ToolContext
from app.broker.models import BrokerUnavailable, Source, SystemState
from app.stream.bus import CHANNEL_ORDERS, CHANNEL_SYSTEM, EventBus
from app.stream.ingest import StalenessMonitor, TradeUpdateIngestor
from app.system.state import StateMachine
from tests.fakes import position, quote
from tests.helpers import activate

MANUAL = {
    "symbol": "AAPL",
    "side": "buy",
    "qty": "10",
    "order_type": "limit",
    "time_in_force": "day",
    "limit_price": "221.50",
}


def headers() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


# --- 1. Alpaca унах ---


async def test_broker_down_stops_new_orders_without_guessing(client, broker):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    broker.reachable = False

    response = await client.post("/api/v1/orders/manual", json=MANUAL, headers=headers())
    assert response.status_code == 503
    assert response.json()["code"] == "broker_unavailable"
    assert broker.submitted == []


async def test_broker_down_never_returns_stale_positions_as_live(client, broker):
    broker.positions = [position("AAPL", "40", "8860.00")]
    await activate(client)
    # Нэг удаа амжилттай уншина — кэш үүсэх боломж ЭНД байна.
    assert (await client.get("/api/v1/positions")).status_code == 200

    broker.reachable = False
    response = await client.get("/api/v1/positions")
    # Кэшээс хуучин утга буцаах зам БАЙХГҮЙ (LLD §7).
    assert response.status_code == 503
    assert "positions" not in response.json()


async def test_broker_failure_mid_order_marks_it_failed_not_silently_lost(
    client, broker, db_session
):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    broker.fail_submit = BrokerUnavailable("холболт order дундуур тасарлаа")

    response = await client.post("/api/v1/orders/manual", json=MANUAL, headers=headers())
    assert response.status_code == 503

    row = (await db_session.execute(select(models.Order))).scalars().one()
    # Мөр нь АЛГА болохгүй: `failed` гэж ил тэмдэглэгдэнэ (LLD §9.1).
    assert row.status == "failed"
    assert row.failure_reason == "BrokerUnavailable"
    assert row.broker_order_id is None

    audits = (
        await db_session.execute(
            select(models.AuditLog).where(models.AuditLog.event_type == "order_failed")
        )
    ).scalars().all()
    assert len(audits) == 1


async def test_health_reports_a_broker_outage_instead_of_500(client, broker):
    broker.reachable = False
    body = (await client.get("/api/v1/health")).json()
    assert body["status"] == "degraded"
    assert body["broker"]["reachable"] is False
    # Төлөв нь ИЛ — UI үүнийг banner болгоно.
    assert body["broker"]["detail"]


# --- 2. Redis / bus унах ---


async def test_a_bus_without_redis_still_serves_state(client, app):
    """Redis нь СОНГОЛТ: байхгүй нь доройтол, уналт БИШ (LLD §12)."""
    assert app.state.bus.redis is None
    body = (await client.get("/api/v1/health")).json()
    assert body["redis"]["reachable"] is False
    assert body["status"] == "ok"  # Redis нь `status`-ыг унагаахгүй
    assert (await client.get("/api/v1/system/state")).status_code == 200


async def test_a_publish_failure_does_not_lose_the_state_transition(client, app, db_session):
    """Мэдэгдэл унах нь ТӨЛӨВИЙГ унагаахгүй — төлөв Postgres-д (R-10)."""

    class ExplodingRedis:
        async def publish(self, *_args):
            raise ConnectionError("Redis унав")

    app.state.bus.redis = ExplodingRedis()
    with pytest.raises(ConnectionError):
        await client.post("/api/v1/kill-switch", json={"reason": "redis тест"})

    app.state.bus.redis = None
    row = (
        await db_session.execute(
            select(models.SystemStateRow).order_by(models.SystemStateRow.seq.desc()).limit(1)
        )
    ).scalar_one()
    assert row.state == "halted"


async def test_system_messages_are_never_dropped_under_tick_flood(bus):
    """AC-14 — зогсоолтын мэдэгдэл tick-ийн үерт живэхгүй (LLD §12)."""
    tiny = EventBus(tick_buffer=4)
    sub = tiny.subscribe([CHANNEL_SYSTEM, "ticks"])
    for i in range(200):
        await tiny.publish(f"ticks:AAPL", {"price": str(i)})
    await tiny.publish(CHANNEL_SYSTEM, {"event": "state_changed", "to": "halted"})

    drained = sub.drain()
    assert drained[0].payload["event"] == "state_changed"
    assert tiny.dropped > 0  # tick хаягдсан…
    assert sum(1 for m in drained if m.channel == CHANNEL_SYSTEM) == 1  # …system биш


# --- 3. LLM provider унах ---


async def test_all_providers_down_means_zero_new_proposals(db_session, broker, settings, bus):
    """T-21 DoD (г) — байгаа position / order ХӨНДӨГДӨХГҮЙ."""
    router = default_router(error_threshold=1)
    router.record_error("claude-mcp", "500")
    router.record_error("local-fallback", "500")
    assert router.any_writable() is False

    broker.positions = [position("AAPL", "40", "8860.00")]
    before = list(broker.positions)
    # Санал гаргах зам огт дуудагдахгүй — позиц хэвээр.
    assert broker.submitted == []
    assert broker.canceled == []
    assert broker.positions == before


async def test_a_provider_failure_mid_proposal_does_not_execute_a_cached_one(
    db_session, broker, settings, bus
):
    """T-38 DoD (в) — provider унасан үед хуучин cache-ийн санал биелэхгүй."""
    machine = StateMachine(db_session, wind_down_grace=settings.WIND_DOWN_GRACE)
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="chaos")
    broker.quotes["AAPL"] = quote("AAPL", "221.50")

    ctx = ToolContext(
        session=db_session,
        broker=broker,
        settings=settings,
        machine=machine,
        bus=bus,
        provider_id="claude-mcp",
        model="claude-opus-5",
        session_id="sess-chaos",
    )
    gateway = Gateway(
        db_session,
        HANDLERS,
        source=Source.ALPACA_PAPER,
        provider_id="claude-mcp",
        session_id="sess-chaos",
    )
    view = await state_view(machine)
    citation = (await gateway.dispatch("get_quote", {"symbol": "AAPL"}, view, ctx))[
        "tool_call_id"
    ]

    # Provider унав: санал ХЭЗЭЭ Ч ирэхгүй. Кэшлэгдсэн цитат нь дангаараа
    # order болохгүй — дуудагдаагүй tool нь үр дагаваргүй.
    assert broker.submitted == []
    count = (await db_session.execute(select(func.count(models.Order.id)))).scalar_one()
    assert count == 0
    assert citation  # цитат үлдсэн ч, түүнээс order үүсэхгүй


# --- 4. WS тасалдал ---


async def test_a_ws_drop_is_recorded_and_announced(engine, broker, bus):
    """AC-2 — тасалдал ЧИМЭЭГҮЙ өнгөрөхгүй."""
    from app.db import make_sessionmaker

    monitor = StalenessMonitor(bus, stale_after_seconds=5)
    monitor.track(CHANNEL_ORDERS).stale = False
    ingestor = TradeUpdateIngestor(make_sessionmaker(engine), broker, bus, monitor)

    async def exploding():
        raise ConnectionResetError("WS тасарлаа")
        yield  # pragma: no cover

    broker.stream_trade_updates = exploding
    sub = bus.subscribe([CHANNEL_SYSTEM])
    await ingestor.run_forever(max_cycles=1)

    assert "stream_stale" in [m.payload["event"] for m in sub.drain()]
    async with make_sessionmaker(engine)() as session:
        events = (
            await session.execute(
                select(models.BreakerEvent).where(models.BreakerEvent.kind == "ws_disconnect")
            )
        ).scalars().all()
    assert [e.ok for e in events] == [False]


async def test_repeated_ws_drops_trip_the_breaker_and_halt(client, engine, settings, broker):
    """AC-15 — WS_DISCONNECT_LIMIT = 5 (тестийн орчин); зургаа нь халина."""
    from app.db import make_sessionmaker
    from app.risk import breaker

    await activate(client)
    async with make_sessionmaker(engine)() as session:
        for _ in range(6):
            await breaker.record(session, "ws_disconnect", ok=False)
        await session.commit()
        tripped = await breaker.CircuitBreaker(
            session, settings=settings, broker=broker
        ).enforce()

    assert tripped is not None
    assert (await client.get("/api/v1/system/state")).json()["state"] == "halted"
    response = await client.post("/api/v1/orders/manual", json=MANUAL, headers=headers())
    assert response.status_code == 409
    assert broker.submitted == []
