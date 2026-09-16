"""Төлөвийн машины endpoint-ууд (T-15, T-16, T-51 backend · FR-7, FR-13).

Гурван товч, гурван ӨӨР утга:
- `POST /kill-switch`      — ТЭР ДОР НЬ зогсоо. Баталгаажуулалт ШААРДАХГҮЙ:
                             яаралтай хаалтын замд саад тавихгүй.
- `POST /system/wind-down` — эхлээд хаах цонх (grace), дараа нь автоматаар halt.
- `POST /system/activate`  — `ACTIVE` руу буцах ЦОРЫН ГАНЦ зам. Баталгаажуулалт
                             ЗААВАЛ + breaker-ийн метрик ДАХИН хэмжигдэнэ.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Request

from app.api.confirm import consume, issue
from app.api.deps import SessionDep, StateMachineDep
from app.api.envelope import envelope
from app.api.problem import problem
from app.api.routes_read import current_source
from app.broker.models import SystemState
from app.risk.breaker import CircuitBreaker
from app.system.state import InvalidTransition
from app.util.time import to_iso

router = APIRouter()


async def state_body(request: Request, machine, session) -> dict:
    row = await machine.current()
    breaker = CircuitBreaker(
        session,
        settings=request.app.state.settings,
        broker=request.app.state.broker,
        publisher=request.app.state.publish_system,
    )
    readings = await breaker.measure()
    return envelope(
        {
            "state": row.state.value,
            "reason": row.reason,
            "changed_at": to_iso(row.changed_at),
            "changed_by": row.changed_by,
            "wind_down_deadline": to_iso(row.wind_down_deadline),
            "seconds_remaining": row.seconds_remaining,
            "breaker_metrics": [r.to_json() for r in readings],
        },
        source=current_source(request),
        system_state=row.state,
    )


@router.get("/system/state", operation_id="getSystemState")
async def get_system_state(request: Request, machine: StateMachineDep, session: SessionDep):
    return await state_body(request, machine, session)


@router.post("/kill-switch", operation_id="postKillSwitch")
async def post_kill_switch(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    body: dict = Body(default_factory=dict),
):
    """Идемпотент. Байгаа позицыг АВТОМАТААР ХААХГҮЙ (спек A-2, AC-16)."""
    await machine.transition(
        SystemState.HALTED,
        by="operator",
        reason=body.get("reason") or "Operator kill switch",
    )
    request.app.state.current_state = SystemState.HALTED
    return await state_body(request, machine, session)


@router.post("/system/wind-down", operation_id="postSystemWindDown")
async def post_wind_down(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    body: dict = Body(default_factory=dict),
):
    """«Би машинаа удахгүй унтраана» — agent-д хаах цонх өгнө (FR-13, AC-34)."""
    try:
        row = await machine.transition(
            SystemState.WINDING_DOWN,
            by="operator",
            reason=body.get("reason") or "Operator: унтраах бэлтгэл",
        )
    except InvalidTransition as exc:
        raise problem("system_halted", 409, exc.detail) from exc
    request.app.state.current_state = row.state
    return await state_body(request, machine, session)


@router.post("/system/activate", operation_id="postSystemActivate")
async def post_activate(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    body: dict = Body(default_factory=dict),
):
    settings = request.app.state.settings
    current = await machine.current()
    if current.state is SystemState.ACTIVE:
        raise problem("already_active", 409, "систем аль хэдийн идэвхтэй")

    # 1) Breaker-ийн метрикийг ДАХИН хэмжинэ. Хадгалагдсан «цэвэрлэсэн» туг
    #    БАЙХГҮЙ — тиймээс түүнийг гараар асаах замаар тойрох боломжгүй.
    breaker = CircuitBreaker(
        session,
        settings=settings,
        broker=request.app.state.broker,
        publisher=request.app.state.publish_system,
    )
    tripped = await breaker.tripped()
    if tripped:
        raise problem(
            "breaker_still_tripped",
            409,
            "circuit breaker-ийн метрик босгоосоо дээр хэвээр — runbook §3-ыг үз",
            breaker_metrics=[r.to_json() for r in tripped],
        )

    # 2) Баталгаажуулалт. Token-гүй бол сорилт буцаана.
    token = body.get("confirmation_token")
    challenge_payload = {"action": "system_activate"}
    if not token:
        raise problem(
            "confirmation_required",
            409,
            "идэвхжүүлэхийн өмнө ил баталгаажуулалт шаардлагатай",
            confirmation=await issue(
                session, "system_activate", challenge_payload, ttl=settings.CONFIRMATION_TTL
            ),
        )
    await consume(session, token, "system_activate", challenge_payload)

    row = await machine.transition(
        SystemState.ACTIVE, by="operator", reason=body.get("note") or "operator activate"
    )
    request.app.state.current_state = row.state
    return await state_body(request, machine, session)
