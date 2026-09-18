"""T-44 / T-15 / T-16 (ID=642, ID=643, ID=669) — арилжааны төлөвийн машин.

LLD §6-ийн шилжилтийн хүснэгтийг мөр мөрөөр нь шалгана (FR-13, AC-34…AC-37).
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import models
from app.broker.models import SystemState
from app.system.state import InvalidTransition, StateMachine
from app.util.time import now_utc

GRACE = timedelta(seconds=900)


@pytest.fixture
async def machine(db_session):
    return StateMachine(db_session, wind_down_grace=GRACE)


async def test_startup_reads_state_never_assumes_active(machine, db_session):
    """LLD §6.3 / AC-37 — мөр байхгүй бол хамгийн АЮУЛГҮЙ төлөв."""
    row = await machine.ensure_initialised()
    assert row.state == SystemState.HALTED
    assert row.reason == "initial_deploy"


async def test_active_to_winding_down_sets_deadline(machine):
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="эхлүүлэв")
    row = await machine.transition(
        SystemState.WINDING_DOWN, by="operator", reason="машинаа унтраана"
    )
    assert row.state == SystemState.WINDING_DOWN
    assert row.wind_down_deadline is not None
    remaining = (row.wind_down_deadline - now_utc()).total_seconds()
    assert 890 < remaining <= 900


async def test_wind_down_is_idempotent_and_never_extends_deadline(machine):
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="эхлүүлэв")
    first = await machine.transition(SystemState.WINDING_DOWN, by="operator", reason="1")
    second = await machine.transition(SystemState.WINDING_DOWN, by="operator", reason="2")
    assert second.wind_down_deadline == first.wind_down_deadline
    assert second.seq == first.seq  # шинэ мөр үүсээгүй


async def test_kill_switch_from_any_live_state(machine):
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="эхлүүлэв")
    await machine.transition(SystemState.WINDING_DOWN, by="operator", reason="унтраана")
    row = await machine.transition(SystemState.HALTED, by="operator", reason="ЗОГСОО")
    assert row.state == SystemState.HALTED
    assert row.wind_down_deadline is None


async def test_halted_to_winding_down_is_not_a_transition(machine):
    """LLD §6.1 — зориудаар БАЙХГҮЙ шилжилт."""
    await machine.ensure_initialised()
    with pytest.raises(InvalidTransition) as exc:
        await machine.transition(SystemState.WINDING_DOWN, by="operator", reason="бага зэрэг")
    assert exc.value.code == "already_halted"


async def test_activate_from_halted(machine):
    await machine.ensure_initialised()
    row = await machine.transition(SystemState.ACTIVE, by="operator", reason="идэвхжүүлэв")
    assert row.state == SystemState.ACTIVE


async def test_activate_when_already_active_is_conflict(machine):
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="1")
    with pytest.raises(InvalidTransition) as exc:
        await machine.transition(SystemState.ACTIVE, by="operator", reason="2")
    assert exc.value.code == "already_active"


async def test_every_transition_writes_one_audit_row(machine, db_session):
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="эхлүүлэв")
    await machine.transition(SystemState.WINDING_DOWN, by="operator", reason="унтраана")
    await machine.transition(SystemState.HALTED, by="circuit_breaker", reason="daily_loss")
    rows = (
        (await db_session.execute(select(models.AuditLog).order_by(models.AuditLog.seq)))
        .scalars()
        .all()
    )
    assert [r.event_type for r in rows] == ["state_changed"] * 4
    assert rows[-1].actor == "system:circuit_breaker"
    assert rows[-1].payload["to"] == "halted"


async def test_grace_expiry_moves_to_halted(machine):
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="эхлүүлэв")
    await machine.transition(
        SystemState.WINDING_DOWN, by="operator", reason="унтраана", grace=timedelta(seconds=-1)
    )
    changed = await machine.sweep_expired_grace()
    assert changed is not None and changed.state == SystemState.HALTED
    assert changed.changed_by == "scheduler"


async def test_restart_while_grace_expired_wakes_halted(db_session):
    """AC-37 — унтарсан цагийг grace-аас ХАСАХГҮЙ."""
    machine = StateMachine(db_session, wind_down_grace=GRACE)
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="эхлүүлэв")
    await machine.transition(
        SystemState.WINDING_DOWN, by="operator", reason="унтраана", grace=timedelta(seconds=-5)
    )
    # Шинэ процесс — кэш хоосон, DB-ээс уншина.
    reborn = StateMachine(db_session, wind_down_grace=GRACE)
    row = await reborn.ensure_initialised()
    assert row.state == SystemState.HALTED
    assert row.reason == "grace_expired_while_down"


async def test_state_is_read_from_db_not_memory(db_session):
    """LLD §6.3 — эх сурвалж нь Postgres, Redis биш."""
    a = StateMachine(db_session, wind_down_grace=GRACE)
    b = StateMachine(db_session, wind_down_grace=GRACE)
    await a.ensure_initialised()
    await a.transition(SystemState.ACTIVE, by="operator", reason="эхлүүлэв")
    assert (await b.current()).state == SystemState.ACTIVE


async def test_publish_happens_after_commit(machine, db_session):
    """LLD §6.2 — commit → ДАРАА нь нийтлэх. Эсрэгээр бол клиент DB-д
    байхгүй төлөв харах цонх үүснэ."""
    seen: list[tuple[str, int]] = []

    async def publisher(event):
        rows = (await db_session.execute(select(models.SystemStateRow))).scalars().all()
        seen.append((event["to"], len(rows)))

    machine.publisher = publisher
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="эхлүүлэв")
    assert seen[-1] == ("active", 2)


# --- B-1: шилжилтийн мөрийн lock (LLD §6.2-ийн 1-р алхам) ---


def test_transition_reads_the_row_with_for_update():
    """Postgres дээр `SELECT ... FOR UPDATE` бодитоор гарна.

    SQLite нь мөрийн lock-ыг дэмждэггүй тул тестийн DB дээр энэ заалт
    хаягдана — компиляцийн шалгалт нь prod-ийн диалект дээрх ЯГ тэр
    statement-ыг хардаг цорын ганц зам.
    """
    from sqlalchemy.dialects import postgresql

    from app.system.state import locked_state_stmt

    sql = str(locked_state_stmt().compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql.upper()


async def test_transition_ignores_the_read_cache(db_session):
    """Кэшлэгдсэн төлөв дээр шийдвэр гаргах нь уралдааны цонх (B-1).

    `enforce_breaker` (5s) ба API-ийн `activate` нэг event loop дээр
    ажиллана: хуучин утга дээр шийдвэрлэвэл унасан метриктэй атлаа
    `active` үлдэх боломж үүснэ.
    """
    writer = StateMachine(db_session, wind_down_grace=GRACE)
    reader = StateMachine(db_session, wind_down_grace=GRACE)
    await writer.ensure_initialised()
    await reader.current()  # reader-ийн кэшид `halted` суув
    await writer.transition(SystemState.ACTIVE, by="operator", reason="эхлүүлэв")

    # Кэш нь `halted` гэж хэлж байгаа ч DB нь `active` — шилжилт нь DB-г
    # уншина, тиймээс давхар идэвхжүүлэлт 409.
    with pytest.raises(InvalidTransition) as exc:
        await reader.transition(SystemState.ACTIVE, by="operator", reason="давхар")
    assert exc.value.code == "already_active"
