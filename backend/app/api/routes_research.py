"""Research cycle-ийн статус + гараар ажиллуулах (T-99, хувийн төсөл).

`POST /research/run-now` нь `run_research_cycle`-ийг ДАРАА нь хийхээр
хүлээхгүй шууд ажиллуулна (fire-and-forget) — LLM дуудлага хэдэн арван
секунд үргэлжлэх тул хүсэлтийг блоклохгүй. Job-ийн дараагийн хуваарийг
ЯГ `RESEARCH_INTERVAL_SECONDS`-аар шинэчилнэ — давхар ажиллахгүй.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.agents.watchlist import get_active_symbols, set_active_symbols
from app.api.deps import SessionDep, StateMachineDep
from app.api.envelope import envelope
from app.api.problem import problem
from app.api.routes_read import current_source
from app.util.time import now_utc, to_iso

router = APIRouter()

JOB_ID = "run_research_cycle"


@router.get("/research/status", operation_id="getResearchStatus")
async def get_research_status(request: Request, machine: StateMachineDep, session: SessionDep):
    state_obj = request.app.state
    scheduler = getattr(state_obj, "scheduler", None)
    job = scheduler.get_job(JOB_ID) if scheduler is not None else None
    state = await machine.current()
    return envelope(
        {
            "next_run_at": to_iso(job.next_run_time) if job is not None else None,
            "interval_seconds": state_obj.settings.RESEARCH_INTERVAL_SECONDS,
            "running": bool(getattr(state_obj, "research_running", False)),
            "symbols": await get_active_symbols(session, state_obj.settings),
            "available_symbols": state_obj.settings.research_symbols,
        },
        source=current_source(request),
        system_state=state.state,
    )


class WatchlistBody(BaseModel):
    symbols: list[str] = Field(min_length=1)


@router.put("/research/watchlist", operation_id="putResearchWatchlist")
async def put_research_watchlist(
    request: Request, machine: StateMachineDep, session: SessionDep, body: WatchlistBody
):
    try:
        active = await set_active_symbols(session, body.symbols, request.app.state.settings)
    except ValueError as exc:
        raise problem("invalid_request", 422, str(exc)) from exc
    state = await machine.current()
    return envelope(
        {"symbols": active}, source=current_source(request), system_state=state.state
    )


@router.post("/research/run-now", operation_id="postResearchRunNow")
async def post_research_run_now(request: Request, machine: StateMachineDep):
    from app.agents.runner import run_research_cycle

    state_obj = request.app.state
    scheduler = getattr(state_obj, "scheduler", None)

    async def _run() -> None:
        state_obj.research_running = True
        try:
            await run_research_cycle(
                state_obj.sessionmaker,
                state_obj.settings,
                state_obj.broker,
                state_obj.publish_system,
                state_obj.provider_router,
                state_obj.bus,
            )
        finally:
            state_obj.research_running = False

    asyncio.create_task(_run())
    if scheduler is not None:
        scheduler.modify_job(
            JOB_ID,
            next_run_time=now_utc() + timedelta(seconds=state_obj.settings.RESEARCH_INTERVAL_SECONDS),
        )
    state = await machine.current()
    return envelope({"triggered": True}, source=current_source(request), system_state=state.state)
