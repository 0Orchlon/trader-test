"""Гар позицийг ашигтай болмогц авто-хаах toggle-ийн API (T-99, хувийн
төсөл, LLD-д тусгаагүй)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.deps import SessionDep, StateMachineDep
from app.api.envelope import envelope
from app.api.routes_read import current_source
from app.execution.manual_take_profit import get_enabled, set_enabled

router = APIRouter()


@router.get("/manual-take-profit", operation_id="getManualTakeProfit")
async def get_manual_take_profit(
    request: Request, machine: StateMachineDep, session: SessionDep
):
    state = await machine.current()
    return envelope(
        {"enabled": await get_enabled(session)},
        source=current_source(request),
        system_state=state.state,
    )


class ManualTakeProfitBody(BaseModel):
    enabled: bool


@router.put("/manual-take-profit", operation_id="putManualTakeProfit")
async def put_manual_take_profit(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    body: ManualTakeProfitBody,
):
    enabled = await set_enabled(session, body.enabled)
    state = await machine.current()
    return envelope(
        {"enabled": enabled}, source=current_source(request), system_state=state.state
    )
