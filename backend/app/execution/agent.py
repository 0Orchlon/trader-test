"""Execution Agent — `BrokerPort.submit_order`-ийн ЦОРЫН ГАНЦ дуудагч (LLD §10).

Статик хаалга R-1 (`tests/static/test_import_gates.py`) нь энэ модулиас гадна
`submit_order` дуудагдахгүйг барина. Хоёр дахь давхарга нь төрлийн систем:
`ValidatedOrder`-ыг зөвхөн `risk.agent.evaluate()`-ийн APPROVE салаа үүсгэнэ.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.audit.chain import AuditChain
from app.broker.models import (
    BrokerUnavailable,
    Origin,
    OrderStatus,
    SystemState,
    ValidatedOrder,
)
from app.util.time import now_utc


class ExecutionAgent:
    def __init__(self, session: AsyncSession, broker, state_machine, *, mode: str) -> None:
        self.session = session
        self.broker = broker
        self.state_machine = state_machine
        self.mode = mode

    async def submit(
        self,
        order: ValidatedOrder,
        *,
        origin: Origin,
        origin_detail: str | None,
        decision_id: UUID | None = None,
        approval_id: UUID | None = None,
        actor: str = "system:execution",
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> models.Order:
        existing = (
            await self.session.execute(
                select(models.Order).where(models.Order.client_order_id == order.client_order_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            # Ижил `client_order_id` = ижил санаа. Шинэ submit БАЙХГҮЙ (LLD §9.2).
            return existing

        # 1) DB бичилт нь Alpaca дуудалтаас ӨМНӨ.
        row = models.Order(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side.value,
            qty=order.qty,
            order_type=order.order_type.value,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            time_in_force=order.time_in_force.value,
            status=OrderStatus.PENDING_RISK.value,
            origin=origin.value,
            origin_detail=origin_detail,
            decision_id=decision_id,
            approval_id=approval_id,
            risk_evaluation=order.risk_evaluation,
            mode=self.mode,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            submitted_at=now_utc(),
        )
        self.session.add(row)
        await self.session.commit()

        # 2) TOCTOU: Risk-ийн шалгалтаас хойш kill switch дарагдсан байж болно.
        #    Кэшийг ТОЙРЧ уншина — эс бөгөөс энэ шалгалт нь route-ийн уншилтыг
        #    давтаад зогсоно (N-2).
        state = await self.state_machine.current(fresh=True)
        if state.state is SystemState.HALTED:
            await self._fail(row, "halted_before_submit")
            raise BrokerUnavailable("систем halted — илгээгдсэнгүй")

        # 3) Alpaca руу.
        try:
            broker_order = await self.broker.submit_order(order)
        except Exception as exc:
            await self._fail(row, type(exc).__name__)
            raise

        row.broker_order_id = broker_order.broker_order_id
        row.status = broker_order.status.value
        row.filled_qty = broker_order.filled_qty
        await AuditChain(self.session).append(
            "order_submitted",
            actor,
            {
                "client_order_id": row.client_order_id,
                "broker_order_id": row.broker_order_id,
                "symbol": row.symbol,
                "side": row.side,
                "qty": str(row.qty),
                "origin": row.origin,
                "origin_detail": row.origin_detail,
                "mode": row.mode,
                "risk_evaluation": row.risk_evaluation,
            },
        )
        await self.session.commit()
        return row

    async def _fail(self, row: models.Order, reason: str) -> None:
        row.status = OrderStatus.FAILED.value
        row.failure_reason = reason
        await AuditChain(self.session).append(
            "order_failed",
            "system:execution",
            {"client_order_id": row.client_order_id, "reason": reason},
        )
        await self.session.commit()
