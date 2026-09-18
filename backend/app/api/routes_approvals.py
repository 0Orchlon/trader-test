"""Approval queue-ийн endpoint-ууд (T-17 · FR-4, AC-5, AC-6).

`approve` нь хөлдөөсөн шийдвэрийг сохроор гүйцэтгэхгүй — Risk-ийг ДАХИН
ажиллуулна. TTL-ийн цонх дотор зах зээл хөдөлж, kill switch дарагдаж, эсвэл
систем wind-down руу орсон байж болно. «Хүн зөвшөөрсөн» нь §7-ийн хязгаарыг
нээх шалтгаан биш — ЗӨВХӨН `MAX_ORDER_NOTIONAL`-ийн escalate-ийг нээнэ.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import models
from app.api.deps import SessionDep, StateMachineDep
from app.api.envelope import envelope
from app.api.problem import problem
from app.api.risk_context import build as build_risk_context
from app.api.routes_read import current_source
from app.api.serializers import approval_json, order_event, order_json
from app.approvals.queue import (
    APPROVED,
    EXPIRED,
    PENDING,
    REJECTED,
    intent_from,
    origin_detail_of,
)
from app.audit.chain import AuditChain
from app.broker.models import BrokerUnavailable, Origin, RiskDecision, SystemState
from app.execution.agent import ExecutionAgent
from app.risk.agent import evaluate
from app.stream.bus import CHANNEL_ORDERS
from app.util.time import now_utc

router = APIRouter()

OPERATOR = "operator"


class ApproveBody(BaseModel):
    expected_version: int
    note: str | None = Field(default=None, max_length=1000)


class RejectBody(BaseModel):
    expected_version: int
    reason: str = Field(min_length=1, max_length=1000)


@router.get("/approvals", operation_id="getApprovals")
async def get_approvals(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    state: Literal["pending", "approved", "rejected", "expired", "all"] = Query("pending"),
):
    stmt = select(models.Approval).order_by(models.Approval.created_at)
    if state != "all":
        stmt = stmt.where(models.Approval.state == state)
    rows = (await session.execute(stmt)).scalars().all()
    current = await machine.current()
    return envelope(
        {"approvals": [approval_json(row) for row in rows]},
        source=current_source(request),
        system_state=current.state,
    )


def locked_approval_stmt(approval_id: uuid.UUID):
    """Мөрийг LOCK-лож уншина (LLD §15.3).

    `session.get` + версь харьцуулалт нь атом биш: зэрэгцээ хоёр `approve`
    хоёулаа шалгалтыг давна. Төлөвийн машинтай ИЖИЛ хэв маяг — SQLite дээр
    заалт хаягдана, Postgres дээр мөрийн lock болно.
    """
    return select(models.Approval).where(models.Approval.id == approval_id).with_for_update()


async def _locked(session, approval_id: uuid.UUID, expected_version: int) -> models.Approval:
    """Мөрийг олж, шийдэгдээгүй + хугацаа дуусаагүй + версь таарсныг шалгана.

    Дараалал: `not_found` → `version_conflict` → хугацаа → бусад шийдэгдсэн.
    Версийн зөрүү ХАМГИЙН ЭХЭНД: operator хуучин дэлгэцээс товч дарсан бол
    түүнд «юу өөрчлөгдсөн бэ» гэдгийг хэлэх нь зөв. Хугацаа нь шийдэгдсэн
    төлөвөөс ДЭЭГҮҮР: `expired` мөрд «версийн зөрүү» гэж хэлэх нь шалтгааныг
    нуух болно.
    """
    row = (await session.execute(locked_approval_stmt(approval_id))).scalar_one_or_none()
    if row is None:
        raise problem("not_found", 404, f"approval олдсонгүй: {approval_id}")
    if row.version != expected_version:
        raise problem(
            "version_conflict",
            409,
            f"хүлээгдсэн version={expected_version}, бодит нь {row.version}",
        )
    if row.state == EXPIRED or (row.state == PENDING and row.expires_at <= now_utc()):
        # Reaper хожимдсон ч хугацаа дууссан мөр гүйцэтгэгдэхгүй (AC-6).
        # Хоёр эх сурвалж — мөрийн төлөв БА цаг — аль нэг нь хангалттай.
        raise problem("approval_expired", 409, "зөвшөөрлийн хугацаа дууссан")
    if row.state != PENDING:
        raise problem("version_conflict", 409, f"мөр аль хэдийн шийдэгдсэн: {row.state}")
    return row


@router.post(
    "/approvals/{approval_id}/approve",
    status_code=202,
    operation_id="postApprovalsByApprovalIdApprove",
)
async def post_approve(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    body: ApproveBody,
    approval_id: Annotated[uuid.UUID, Path()],
):
    settings = request.app.state.settings
    broker = request.app.state.broker
    row = await _locked(session, approval_id, body.expected_version)

    state = await machine.current()
    if state.state is SystemState.HALTED:
        # Мөрийг `pending` хэвээр үлдээнэ: operator дараа дахин үзэх эрхтэй.
        raise problem("system_halted", 409, "Систем зогссон — зөвшөөрөл гүйцэтгэгдэхгүй")

    intent = intent_from(row.proposed_order)
    try:
        ctx = await build_risk_context(
            broker,
            settings,
            state.state,
            intent.symbol,
            idempotency_key=str(row.id),
            session=session,
        )
    except BrokerUnavailable as exc:
        raise problem("broker_unavailable", 503, str(exc)) from exc

    # Хүний зөвшөөрөл нь ЗӨВХӨН escalate-ийн хаалгыг нээнэ (LLD §8.1).
    evaluation = evaluate(ctx, intent, escalation_confirmed=True)
    if evaluation.decision is RiskDecision.REJECT:
        failed = {c.rule for c in evaluation.checks if not c.passed}
        code = (
            "winding_down_increase_blocked"
            if "wind_down_direction" in failed
            else "risk_rejected"
        )
        raise problem(code, 422, evaluation.reason or "", risk=evaluation.to_contract())

    agent = ExecutionAgent(session, broker, machine, mode=settings.mode.value)
    order = await agent.submit(
        evaluation.validated_order,
        origin=Origin.RESEARCH_AGENT,
        origin_detail=origin_detail_of(row.proposed_order),
        decision_id=row.decision_id,
        approval_id=row.id,
        actor=OPERATOR,
    )

    row.state = APPROVED
    row.version += 1
    row.resolved_at = now_utc()
    row.resolved_by = OPERATOR
    row.resolution_reason = body.note
    await AuditChain(session).append(
        "approval_resolved",
        OPERATOR,
        {
            "approval_id": str(row.id),
            "resolution": APPROVED,
            "note": body.note,
            "order_id": str(order.id),
        },
    )
    await session.commit()
    await request.app.state.bus.publish(
        CHANNEL_ORDERS, order_event("approval_approved", order, source=current_source(request))
    )
    return envelope(
        {"order": order_json(order), "risk": evaluation.to_contract()},
        source=current_source(request),
        system_state=state.state,
    )


@router.post("/approvals/{approval_id}/reject", operation_id="postApprovalsByApprovalIdReject")
async def post_reject(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    body: RejectBody,
    approval_id: Annotated[uuid.UUID, Path()],
):
    """Буцаах боломжгүй. Татгалзсан санал ХЭЗЭЭ Ч илгээгдэхгүй (AC-5)."""
    row = await _locked(session, approval_id, body.expected_version)
    row.state = REJECTED
    row.version += 1
    row.resolved_at = now_utc()
    row.resolved_by = OPERATOR
    row.resolution_reason = body.reason
    await AuditChain(session).append(
        "approval_resolved",
        OPERATOR,
        {"approval_id": str(row.id), "resolution": REJECTED, "reason": body.reason},
    )
    await session.commit()
    state = await machine.current()
    return envelope(
        {"approval": approval_json(row)},
        source=current_source(request),
        system_state=state.state,
    )
