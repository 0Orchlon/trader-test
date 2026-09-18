"""Order илгээх / цуцлах зам (T-08 · T-47 · FR-12, AC-31…AC-33).

Гарын order нь agent-ийн замтай ЯГ ИЖИЛ хаалгыг дайрна — Risk Agent →
Execution → Alpaca. Энд `submit_order` дуудагдахгүй (статик хаалга R-1):
`app.execution.agent.ExecutionAgent.submit` нь цорын ганц орох цэг.

**Дарааллын шалтгаан.** Төлөвийн шалгалт нь Risk контекст угсрахаас ӨМНӨ:
`halted` үед Alpaca руу уншилт ч явуулахгүй (AC-33). Idempotency нь бүр
түрүүнд: давхардсан хүсэлт нь broker-ийг огт хөндөхгүй.
"""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app import models
from app.api.confirm import consume, issue
from app.api.deps import SessionDep, StateMachineDep
from app.api.envelope import envelope
from app.api.problem import problem
from app.api.risk_context import build as build_risk_context
from app.api.routes_read import current_source
from app.api.serializers import order_event, order_json
from app.audit.chain import AuditChain
from app.broker.models import (
    BrokerUnavailable,
    Origin,
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecision,
    SystemState,
    TimeInForce,
)
from app.execution.agent import ExecutionAgent
from app.execution.idempotency import request_hash
from app.risk.agent import evaluate
from app.stream.bus import CHANNEL_ORDERS

router = APIRouter()

MANUAL_ACTOR = "operator"


class ManualOrderRequest(BaseModel):
    """contracts.yaml `ManualOrderRequest`.

    `grounded_in` / `rationale` ЗОРИУДААР байхгүй — гарын order нь agent-ийн
    санал БИШ тул grounding checker хамаарахгүй (AC-32). `extra="forbid"`:
    гэрээнд байхгүй талбар чимээгүй хаягдахгүй.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    side: OrderSide
    qty: str
    order_type: OrderType
    time_in_force: TimeInForce
    limit_price: str | None = None
    stop_price: str | None = None
    confirmation_token: str | None = None

    def intent(self) -> OrderIntent:
        return OrderIntent(
            symbol=self.symbol.upper(),
            side=self.side,
            qty=_decimal(self.qty, "qty"),
            order_type=self.order_type,
            time_in_force=self.time_in_force,
            limit_price=_decimal(self.limit_price, "limit_price"),
            stop_price=_decimal(self.stop_price, "stop_price"),
        )

    def confirmation_payload(self) -> dict:
        """Баталгаажуулалт нь ORDER-ийн биед уягдана — token авсны дараа
        хэмжээг өсгөх боломжгүй (LLD §8.4)."""
        return self.model_dump(exclude={"confirmation_token"}, mode="json")


def _decimal(value: str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise problem("risk_rejected", 422, f"{field}: тоон утга биш — {value!r}") from exc


def _risk_problem(evaluation) -> None:
    """Risk-ийн татгалзлыг гэрээний `code` рүү буулгана.

    Wind-down-ийн чиглэлийн зөрчил нь ТУСДАА код: operator «яагаад» гэдгийг
    ерөнхий `risk_rejected`-аас биш, шууд уншина (contracts.yaml).
    """
    failed = {c.rule for c in evaluation.checks if not c.passed}
    if "wind_down_direction" in failed:
        raise problem(
            "winding_down_increase_blocked",
            422,
            evaluation.reason or "winding_down үед эрсдэл нэмэгдүүлэхийг хориглов",
            risk=evaluation.to_contract(),
        )
    raise problem(
        "risk_rejected",
        422,
        evaluation.reason or "Risk Agent татгалзав",
        risk=evaluation.to_contract(),
    )


async def _existing_for_key(session, key: str, intent: OrderIntent) -> models.Order | None:
    """Idempotency-ийн бүртгэл (LLD §9.2).

    Зөвхөн `client_order_id`-ийн hash дээр түшиглэвэл ижил key + ӨӨР биетэй
    хүсэлт шинэ order болж дамжина. Тиймээс key нь ТУСАД НЬ хадгалагдаж,
    биеийн hash-тай тулгагдана.
    """
    row = (
        await session.execute(
            select(models.Order).where(models.Order.idempotency_key == key)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.request_hash != request_hash(intent):
        raise problem(
            "idempotency_conflict",
            409,
            "Idempotency-Key давхардсан боловч биеийн агуулга өөр",
        )
    return row


@router.post("/orders/manual", status_code=202, operation_id="postOrdersManual")
async def post_orders_manual(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    body: ManualOrderRequest,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
):
    settings = request.app.state.settings
    broker = request.app.state.broker
    key = str(idempotency_key)
    intent = body.intent()
    source = current_source(request)

    existing = await _existing_for_key(session, key, intent)
    state = await machine.current()
    if existing is not None:
        # Ижил key + ижил бие = ижил хариу. Шинэ submit БАЙХГҮЙ.
        return envelope(
            {"order": order_json(existing), "risk": existing.risk_evaluation},
            source=source,
            system_state=state.state,
        )

    # 1) Төлөв — Alpaca руу дуудалт хийхээс ӨМНӨ (AC-33).
    if state.state is SystemState.HALTED:
        raise problem(
            "system_halted",
            409,
            "Систем зогссон — шинэ order илгээхгүй. Идэвхжүүлэх нь operator-ийн үйлдэл.",
        )

    # 2) Risk-ийн контекст — бүгд бодит уншилт (LLD §8.3).
    try:
        ctx = await build_risk_context(
            broker, settings, state.state, intent.symbol, idempotency_key=key
        )
    except BrokerUnavailable as exc:
        raise problem("broker_unavailable", 503, str(exc)) from exc

    evaluation = evaluate(ctx, intent)
    if evaluation.decision is RiskDecision.REJECT:
        _risk_problem(evaluation)

    # 3) ESCALATE → хоёр шаттай баталгаажуулалт. Approval queue-д мөр
    #    ҮҮСГЭХГҮЙ: operator өөрөө хүсэлтийн нөгөө үзүүрт байна (спек A-8).
    if evaluation.decision is RiskDecision.ESCALATE_TO_HUMAN:
        payload = body.confirmation_payload()
        if not body.confirmation_token:
            raise problem(
                "confirmation_required",
                409,
                evaluation.reason or "хязгаараас дээш — ил баталгаажуулалт шаардлагатай",
                risk=evaluation.to_contract(),
                confirmation=await issue(
                    session, "manual_order", payload, ttl=settings.CONFIRMATION_TTL
                ),
            )
        await consume(session, body.confirmation_token, "manual_order", payload)
        # `ValidatedOrder`-ыг үүсгэх ЦОРЫН ГАНЦ газар нь `evaluate()` (LLD §7)
        # — энд гараар байгуулахгүй, баталгаажсан тугтайгаар ДАХИН үнэлнэ.
        evaluation = evaluate(ctx, intent, escalation_confirmed=True)
    validated = evaluation.validated_order

    if validated is None:  # pragma: no cover - хамгаалалт
        raise problem("risk_rejected", 422, "Risk Agent баталгаажсан order гаргаагүй")

    agent = ExecutionAgent(session, broker, machine, mode=settings.mode.value)
    row = await agent.submit(
        validated,
        origin=Origin.MANUAL_OPERATOR,
        origin_detail=MANUAL_ACTOR,
        actor=MANUAL_ACTOR,
        idempotency_key=key,
        request_hash=request_hash(intent),
    )
    await request.app.state.bus.publish(
        CHANNEL_ORDERS, order_event("order_submitted", row, source=source)
    )
    return envelope(
        {"order": order_json(row), "risk": evaluation.to_contract()},
        source=source,
        system_state=state.state,
    )


@router.post("/orders/{order_id}/cancel", status_code=202, operation_id="postOrdersByOrderIdCancel")
async def post_order_cancel(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    order_id: Annotated[uuid.UUID, Path()],
):
    """Цуцлалт нь эрсдэл БАГАСГАХ үйлдэл — `halted` үед ч зөвшөөрөгдөнө.

    Kill switch нь ШИНЭ order илгээхийг зогсоодог, байгааг цуцлахыг биш
    (спек A-2). Хоёрыг холих нь operator-ыг зогссон системд түгжинэ.
    """
    row = await session.get(models.Order, order_id)
    if row is None:
        raise problem("not_found", 404, f"order олдсонгүй: {order_id}")
    if row.broker_order_id is None:
        raise problem("not_found", 404, "энэ order Alpaca руу хараахан илгээгдээгүй")
    try:
        await request.app.state.broker.cancel_order(row.broker_order_id)
    except BrokerUnavailable as exc:
        raise problem("broker_unavailable", 503, str(exc)) from exc
    await AuditChain(session).append(
        "order_cancel_requested",
        MANUAL_ACTOR,
        {"order_id": str(row.id), "broker_order_id": row.broker_order_id, "symbol": row.symbol},
    )
    await session.commit()
    state = await machine.current()
    return envelope(
        {"order": order_json(row)}, source=current_source(request), system_state=state.state
    )
