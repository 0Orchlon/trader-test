"""T-52 (ID=677) — төлөвийн машины бүтэн E2E (AC-33, AC-36, AC-37).

Мөчлөг: `ACTIVE` → wind-down → нэмэгдүүлэх ТАТГАЛЗАНА / хаах ДАМЖИНА →
grace дуусна → `HALTED` → **процессыг унагаж дахин асаана** → `HALTED`
ХЭВЭЭР → баталгаажуулалтгүй `activate` татгалзана → баталгаажуулалттай
`activate` → `ACTIVE`.

«Процесс дахин асаах»-ыг engine-ийг ХУВААЛЦСАН хоёр дахь `create_app`-аар
загварчилна: DB нь үлдэнэ, process-ийн санах ой алга болно. Энэ нь яг
prod-ийн restart-ийн хэлбэр (LLD §6.3).
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app import models
from app.broker.models import SystemState
from app.main import create_app
from app.system.state import StateMachine
from app.util.time import now_utc
from tests.fakes import position, quote
from tests.helpers import activate, wind_down


def manual_body(**overrides) -> dict:
    base = {
        "symbol": "AAPL",
        "side": "buy",
        "qty": "10",
        "order_type": "limit",
        "time_in_force": "day",
        "limit_price": "221.50",
    }
    base.update(overrides)
    return base


async def post_manual(client, payload: dict):
    return await client.post(
        "/api/v1/orders/manual", json=payload, headers={"Idempotency-Key": str(uuid.uuid4())}
    )


async def restart(engine, settings, broker, bus):
    """Процессыг унагаж дахин асаах загвар: шинэ app, ХУУЧИН DB."""
    application = create_app(engine=engine, settings=settings, broker=broker, bus=bus)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as fresh:
            yield fresh


async def expire_grace(engine):
    """Grace-ийн эцсийн хугацааг өнгөрөөнө — цагийг хөлдөөхийн оронд
    хугацааг нь урагшлуулна (тест хүлээхгүй)."""
    from app.db import make_sessionmaker

    async with make_sessionmaker(engine)() as session:
        row = (
            await session.execute(
                select(models.SystemStateRow).order_by(models.SystemStateRow.seq.desc()).limit(1)
            )
        ).scalar_one()
        row.wind_down_deadline = now_utc() - timedelta(seconds=1)
        await session.commit()


async def test_full_cycle_wind_down_restart_activate(client, broker, engine, settings, bus):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    broker.positions = [position("AAPL", "40", "8860.00")]

    # 1) ACTIVE
    assert (await activate(client)).json()["state"] == "active"

    # 2) wind-down → нэмэгдүүлэх ТАТГАЛЗАНА
    assert (await wind_down(client)).json()["state"] == "winding_down"
    increase = await post_manual(client, manual_body())
    assert increase.status_code == 422
    assert increase.json()["code"] == "winding_down_increase_blocked"

    # 3) …хаах order ДАМЖИНА (agent ашгаа авч хаах цонх)
    reduce = await post_manual(client, manual_body(side="sell", qty="10"))
    assert reduce.status_code == 202, reduce.text
    assert len(broker.submitted) == 1

    # 4) grace дуусна → HALTED (scheduler-ийн sweep)
    await expire_grace(engine)
    from app.db import make_sessionmaker

    async with make_sessionmaker(engine)() as session:
        machine = StateMachine(session, wind_down_grace=settings.WIND_DOWN_GRACE)
        swept = await machine.sweep_expired_grace()
    assert swept is not None and swept.state is SystemState.HALTED

    # (б) Позиц АВТОМАТААР хаагдаагүй — liquidation БАЙХГҮЙ.
    assert [p.qty for p in broker.positions] == [Decimal("40")]
    assert broker.canceled == []

    # 5) Процессыг дахин асаана — төлөв HALTED ХЭВЭЭР (AC-37)
    async for fresh in restart(engine, settings, broker, bus):
        assert (await fresh.get("/api/v1/system/state")).json()["state"] == "halted"

        # 6) Шинэ order = 0
        before = len(broker.submitted)
        blocked = await post_manual(fresh, manual_body(side="sell", qty="5"))
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "system_halted"
        assert len(broker.submitted) == before

        # 7) Баталгаажуулалтгүй `activate` ТАТГАЛЗАНА
        naked = await fresh.post("/api/v1/system/activate", json={})
        assert naked.status_code == 409
        assert naked.json()["code"] == "confirmation_required"
        assert (await fresh.get("/api/v1/system/state")).json()["state"] == "halted"

        # 8) Баталгаажуулалттай `activate` → ACTIVE
        token = naked.json()["confirmation"]["token"]
        resumed = await fresh.post(
            "/api/v1/system/activate", json={"confirmation_token": token}
        )
        assert resumed.status_code == 200
        assert resumed.json()["state"] == "active"


async def test_restart_never_resumes_trading_on_its_own(client, engine, settings, broker, bus):
    """AC-37 — дахин асаалт нь төлөвийг УНШИНА, эхлүүлэхгүй."""
    await activate(client)
    await client.post("/api/v1/kill-switch", json={"reason": "operator"})

    async for fresh in restart(engine, settings, broker, bus):
        body = (await fresh.get("/api/v1/system/state")).json()
        assert body["state"] == "halted"
        assert body["changed_by"] == "operator"


async def test_grace_that_expires_while_down_wakes_up_halted(client, engine, settings, broker, bus):
    """Унтарсан хугацаанд grace дууссан бол сэрэхдээ `halted` (AC-37)."""
    await activate(client)
    await wind_down(client)
    await expire_grace(engine)

    async for fresh in restart(engine, settings, broker, bus):
        body = (await fresh.get("/api/v1/system/state")).json()
        assert body["state"] == "halted"
        assert body["reason"] == "grace_expired_while_down"


async def test_activate_is_refused_while_the_breaker_is_still_tripped(client, broker, db_session):
    """T-16-тай холбоо: шалтгаан цэвэрлээгүй бол идэвхжихгүй (AC-37)."""
    from dataclasses import replace

    await activate(client)
    await client.post("/api/v1/kill-switch", json={"reason": "breaker"})

    # Өдрийн алдагдал хязгаараас доош — DAILY_LOSS_LIMIT = -2000.00.
    broker.account = replace(
        broker.account, equity=Decimal("90000.00"), last_equity=Decimal("100000.00")
    )
    response = await client.post("/api/v1/system/activate", json={})
    assert response.status_code == 409
    assert response.json()["code"] == "breaker_still_tripped"
    assert (await client.get("/api/v1/system/state")).json()["state"] == "halted"


async def test_state_survives_a_bus_without_redis(client, engine, settings, broker):
    """`plan.md` R-10 — төлөв Postgres-д. Redis унах нь төлөвийг алдагдуулахгүй."""
    from app.stream.bus import EventBus

    await activate(client)
    await wind_down(client)

    # Шинэ bus = Redis-гүй, түүхгүй. Төлөв нь DB-ээс уншигдана.
    async for fresh in restart(engine, settings, broker, EventBus()):
        body = (await fresh.get("/api/v1/system/state")).json()
        assert body["state"] == "winding_down"
        assert body["wind_down_deadline"] is not None
