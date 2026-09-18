"""T-15 (ID=642) kill switch · T-16 (ID=643) circuit breaker · T-51-ийн backend.

DoD-ийн голууд:
- kill switch дарснаас хойш гарсан submit = 0, позиц хөндөгдөхгүй (AC-16).
- breaker-ийн метрик БҮР дангаараа halt үүсгэнэ, автомат сэргэлт БАЙХГҮЙ.
- `activate` нь метрикийг ДАХИН хэмжинэ — хадгалсан туг биш (AC-37).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app import models
from app.broker.models import SystemState
from app.util.time import now_utc


async def activate(client, *, note: str = "тест"):
    """Хоёр шаттай: эхний дуудалт 409 + token, хоёр дахь нь token-той."""
    first = await client.post("/api/v1/system/activate", json={})
    if first.status_code != 409 or first.json()["code"] != "confirmation_required":
        # Breaker унасан / аль хэдийн идэвхтэй — дуудагч өөрөө шалгана.
        return first
    token = first.json()["confirmation"]["token"]
    return await client.post(
        "/api/v1/system/activate", json={"confirmation_token": token, "note": note}
    )


async def test_initial_state_is_halted(client):
    body = (await client.get("/api/v1/system/state")).json()
    assert body["state"] == "halted"
    assert body["changed_by"] == "operator"


async def test_activate_requires_confirmation(client):
    response = await client.post("/api/v1/system/activate", json={})
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "confirmation_required"
    # AC-38: сорилтын текст нь үйлдэл тус бүрд ӨӨР — хоёр товчийг андуурахгүй.
    assert "идэвхжүүл" in body["confirmation"]["prompt"].lower()


async def test_activate_with_token_moves_to_active(client):
    response = await activate(client)
    assert response.status_code == 200
    assert response.json()["state"] == "active"


async def test_confirmation_token_is_single_use(client):
    first = await client.post("/api/v1/system/activate", json={})
    token = first.json()["confirmation"]["token"]
    assert (
        await client.post("/api/v1/system/activate", json={"confirmation_token": token})
    ).status_code == 200
    await client.post("/api/v1/kill-switch", json={"reason": "дахин шалгах"})
    replay = await client.post("/api/v1/system/activate", json={"confirmation_token": token})
    assert replay.status_code == 409


async def test_kill_switch_needs_no_confirmation(client):
    await activate(client)
    response = await client.post("/api/v1/kill-switch", json={"reason": "Operator kill switch"})
    assert response.status_code == 200
    assert response.json()["state"] == "halted"


async def test_kill_switch_is_idempotent(client):
    await activate(client)
    await client.post("/api/v1/kill-switch", json={})
    second = await client.post("/api/v1/kill-switch", json={})
    assert second.status_code == 200 and second.json()["state"] == "halted"


async def test_kill_switch_does_not_close_positions(client, broker):
    from tests.fakes import position

    broker.positions = [position("AAPL", "40", "9012.00")]
    await activate(client)
    await client.post("/api/v1/kill-switch", json={})
    body = (await client.get("/api/v1/positions")).json()
    assert [p["qty"] for p in body["positions"]] == ["40"]
    assert broker.canceled == []


async def test_wind_down_sets_deadline_and_seconds_remaining(client):
    await activate(client)
    response = await client.post("/api/v1/system/wind-down", json={"reason": "унтраана"})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "winding_down"
    assert body["wind_down_deadline"] is not None
    assert 0 < body["seconds_remaining"] <= 900


async def test_wind_down_on_halted_is_409(client):
    response = await client.post("/api/v1/system/wind-down", json={})
    assert response.status_code == 409
    assert response.json()["code"] == "already_halted" or response.json()["code"] == "system_halted"


async def test_state_change_is_broadcast_on_system_channel(client, app, bus):
    sub = bus.subscribe(["system"])
    await activate(client)
    events = [m.payload["event"] if "event" in m.payload else m.payload["type"] for m in sub.drain()]
    assert "state_changed" in events


async def test_activate_blocked_while_breaker_tripped(client, broker, db_session):
    """AC-15/AC-37 — «цэвэрлэсэн» туг БАЙХГҮЙ, бодит хэмжилт."""
    broker.account = broker.account.__class__(
        account_id="X",
        equity=Decimal("90000.00"),
        cash=Decimal("0.00"),
        buying_power=Decimal("0.00"),
        last_equity=Decimal("100000.00"),
        pattern_day_trader=False,
        day_trade_count=0,
    )
    response = await activate(client)
    assert response.status_code == 409
    assert response.json()["code"] == "breaker_still_tripped"
    assert any(m["metric"] == "daily_loss" for m in response.json()["breaker_metrics"])


@pytest.mark.parametrize(
    "kind,count,ok_count",
    [("api_error", 20, 0), ("order_reject", 20, 0), ("ws_disconnect", 10, 0)],
)
async def test_each_breaker_metric_trips_alone(client, db_session, kind, count, ok_count):
    for _ in range(count):
        db_session.add(models.BreakerEvent(kind=kind, ok=False, ts=now_utc()))
    for _ in range(ok_count):
        db_session.add(models.BreakerEvent(kind=kind, ok=True, ts=now_utc()))
    await db_session.commit()
    response = await activate(client)
    assert response.status_code == 409
    assert response.json()["code"] == "breaker_still_tripped"


async def test_breaker_does_not_self_heal(client, db_session):
    """Босгын дараа хүлээхэд өөрөө сэргэхгүй — хүн ил үйлдэл хийнэ."""
    for _ in range(20):
        db_session.add(models.BreakerEvent(kind="api_error", ok=False, ts=now_utc()))
    await db_session.commit()
    assert (await activate(client)).status_code == 409
    assert (await client.get("/api/v1/system/state")).json()["state"] == "halted"


async def test_old_events_outside_window_do_not_trip(client, db_session, settings):
    stale_ts = now_utc() - timedelta(seconds=settings.BREAKER_WINDOW + 60)
    for _ in range(50):
        db_session.add(models.BreakerEvent(kind="api_error", ok=False, ts=stale_ts))
    await db_session.commit()
    assert (await activate(client)).status_code == 200


async def test_breaker_metrics_listed_in_state_response(client):
    body = (await client.get("/api/v1/system/state")).json()
    metrics = {m["metric"] for m in body["breaker_metrics"]}
    assert metrics == {"daily_loss", "api_error_rate", "order_reject_rate", "ws_disconnects"}


async def test_breaker_trips_system_to_halted(client, db_session, app):
    """Автомат хаалт: monitor нь kill switch-тэй ИЖИЛ halt үүсгэнэ (AC-15)."""
    from app.risk.breaker import CircuitBreaker

    await activate(client)
    for _ in range(20):
        db_session.add(models.BreakerEvent(kind="order_reject", ok=False, ts=now_utc()))
    await db_session.commit()

    async with app.state.sessionmaker() as session:
        breaker = CircuitBreaker(
            session,
            settings=app.state.settings,
            broker=app.state.broker,
            publisher=app.state.publish_system,
        )
        tripped = await breaker.enforce()
    assert tripped is not None
    assert (await client.get("/api/v1/system/state")).json()["state"] == "halted"


async def test_breaker_works_without_llm_providers(client, app, db_session):
    """AC-15 DoD (г): бүх LLM provider унасан үед ч breaker ажиллана."""
    from app.risk.breaker import CircuitBreaker

    app.state.provider_router = None
    for _ in range(20):
        db_session.add(models.BreakerEvent(kind="api_error", ok=False, ts=now_utc()))
    await db_session.commit()
    async with app.state.sessionmaker() as session:
        breaker = CircuitBreaker(
            session, settings=app.state.settings, broker=app.state.broker, publisher=None
        )
        assert await breaker.enforce() is not None


async def test_grace_expiry_moves_to_halted(client, app):
    """AC-36 — grace дуусахад автоматаар `halted`; позиц хөндөгдөхгүй."""
    from app.system.state import StateMachine

    await activate(client)
    await client.post("/api/v1/system/wind-down", json={})
    async with app.state.sessionmaker() as session:
        row = await StateMachine(session, wind_down_grace=timedelta(seconds=1)).current()
        assert row.state is SystemState.WINDING_DOWN
        # Цаг хөлдөөхийн оронд deadline-ыг ухраана — үр дүн нь ижил, хамаарал бага.
        model = await session.get(models.SystemStateRow, row.seq)
        model.wind_down_deadline = now_utc() - timedelta(seconds=1)
        await session.commit()
        swept = await StateMachine(
            session, wind_down_grace=timedelta(seconds=1)
        ).sweep_expired_grace()
    assert swept.state is SystemState.HALTED


# --- N-2: grace дуусах ЯГ агшинд ажиллах `date` job (LLD §6.4, D-8) ---


class _RecordingScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})
        return kwargs.get("id")


async def test_wind_down_schedules_a_job_at_the_deadline(client, app):
    """10 секундын sweep дангаараа ±10s нарийвчлал өгнө — LLD нь ХОЁУЛАНГ
    шаардсан: `date` job нь яг агшинд, `interval` нь алдагдсан үеийн нөөц."""
    from apscheduler.triggers.date import DateTrigger

    from app.util.time import to_iso

    scheduler = _RecordingScheduler()
    app.state.scheduler = scheduler
    await activate(client)

    body = (await client.post("/api/v1/system/wind-down", json={})).json()
    (job,) = [j for j in scheduler.jobs if j["id"] == "wind_down_deadline"]
    assert isinstance(job["trigger"], DateTrigger)
    assert to_iso(job["trigger"].run_date) == body["wind_down_deadline"]
    assert job["replace_existing"] is True
