"""Agent-ийн шийдвэрийн лог ба provider switcher (T-21 · FR-6, FR-8, AC-7…AC-10).

`GET /agent-decisions/{id}` нь **ТҮҮХИЙ** tool call payload буцаана —
redaction-аас өөр засваргүй (AC-8). Энэ нь «AI яагаад ингэж хэлсэн бэ»
гэдгийн эх сурвалж: дүгнэлт биш, ӨГӨГДӨЛ. Хураангуйлах нь operator-ыг
модельд итгэхээс өөр сонголтгүй болгоно.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from app import models
from app.agents.router import ProviderUnhealthy, UnknownProvider
from app.api.deps import SessionDep, StateMachineDep
from app.api.envelope import envelope
from app.api.problem import problem
from app.api.routes_read import current_source
from app.api.serializers import decision_json, tool_call_json
from app.audit.chain import AuditChain
from app.stream.bus import CHANNEL_SYSTEM
from app.util.time import parse_iso

router = APIRouter()


class SwitchBody(BaseModel):
    provider_id: str


def _router_of(request: Request):
    provider_router = getattr(request.app.state, "provider_router", None)
    if provider_router is None:
        raise problem("provider_unavailable", 503, "provider router тохируулаагүй")
    return provider_router


@router.get("/agent-decisions", operation_id="getAgentDecisions")
async def get_agent_decisions(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    agent: Literal["research", "auto_tuning"] | None = None,
    symbol: str | None = None,
    outcome: str | None = None,
    provider: str | None = None,
    since: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    stmt = select(models.AgentDecision).order_by(models.AgentDecision.created_at.desc())
    if agent:
        stmt = stmt.where(models.AgentDecision.agent == agent)
    if outcome:
        stmt = stmt.where(models.AgentDecision.outcome == outcome)
    if provider:
        stmt = stmt.where(models.AgentDecision.provider == provider)
    if since:
        stmt = stmt.where(models.AgentDecision.created_at >= parse_iso(since))
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    if symbol:
        # `proposal` нь JSON — DB-ээс хамаарсан хайлт бичихгүй, Python талд.
        wanted = symbol.upper()
        rows = [r for r in rows if (r.proposal or {}).get("symbol", "").upper() == wanted]
    state = await machine.current()
    return envelope(
        {"decisions": [decision_json(row) for row in rows]},
        source=current_source(request),
        system_state=state.state,
    )


@router.get("/agent-decisions/{decision_id}", operation_id="getAgentDecisionsByDecisionId")
async def get_agent_decision(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    decision_id: Annotated[uuid.UUID, Path()],
):
    row = await session.get(models.AgentDecision, decision_id)
    if row is None:
        raise problem("not_found", 404, f"шийдвэр олдсонгүй: {decision_id}")
    calls = (
        await session.execute(
            select(models.ToolCall)
            .where(models.ToolCall.session_id == row.session_id)
            .order_by(models.ToolCall.called_at)
        )
    ).scalars().all()
    state = await machine.current()
    return envelope(
        {
            "decision": decision_json(row),
            # AC-8: түүхий payload. Хураангуй БАЙХГҮЙ.
            "tool_calls": [tool_call_json(call) for call in calls],
        },
        source=current_source(request),
        system_state=state.state,
    )


@router.get("/providers", operation_id="getProviders")
async def get_providers(request: Request, machine: StateMachineDep):
    state = await machine.current()
    return envelope(
        _router_of(request).to_json(),
        source=current_source(request),
        system_state=state.state,
    )


@router.post("/providers/{role}/switch", operation_id="postProvidersByRoleSwitch")
async def post_provider_switch(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    body: SwitchBody,
    role: Annotated[str, Path()],
):
    """Restart БАЙХГҮЙ (NFR-4). Нислэг дунд байгаа дуудалт хуучнаар дуусна."""
    provider_router = _router_of(request)
    try:
        result = await provider_router.switch(role, body.provider_id)
    except UnknownProvider as exc:
        raise problem("provider_unavailable", 422, str(exc)) from exc
    except ProviderUnhealthy as exc:
        raise problem("provider_unavailable", 422, str(exc)) from exc

    await AuditChain(session).append("provider_switched", "operator", result.to_json())
    await session.commit()
    await request.app.state.bus.publish(
        CHANNEL_SYSTEM, {"event": "provider_switched", **result.to_json()}
    )
    state = await machine.current()
    return envelope(
        result.to_json(), source=current_source(request), system_state=state.state
    )
