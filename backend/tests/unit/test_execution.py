"""T-13 (ID=640) — Execution Agent (LLD §10, AC-3)."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import models
from app.broker.models import (
    BrokerOrder,
    BrokerUnavailable,
    Origin,
    OrderSide,
    OrderStatus,
    OrderType,
    SystemState,
    TimeInForce,
    ValidatedOrder,
)
from app.execution.agent import ExecutionAgent
from app.system.state import StateMachine
from app.util.time import now_utc

VALIDATED = ValidatedOrder(
    symbol="AAPL",
    side=OrderSide.BUY,
    qty=Decimal("10"),
    order_type=OrderType.LIMIT,
    time_in_force=TimeInForce.DAY,
    limit_price=Decimal("221.50"),
    stop_price=None,
    client_order_id="p3-abc123",
    risk_evaluation={"decision": "APPROVE", "checks": []},
)


class FakeBroker:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.submitted: list[ValidatedOrder] = []
        self.fail = fail

    async def submit_order(self, req: ValidatedOrder) -> BrokerOrder:
        self.submitted.append(req)
        if self.fail:
            raise self.fail
        return BrokerOrder(
            broker_order_id="alpaca-1",
            client_order_id=req.client_order_id,
            symbol=req.symbol,
            side=req.side,
            qty=req.qty,
            filled_qty=Decimal("0"),
            order_type=req.order_type,
            time_in_force=req.time_in_force,
            status=OrderStatus.ACCEPTED,
            submitted_at=now_utc(),
        )


@pytest.fixture
async def active_machine(db_session):
    from datetime import timedelta

    machine = StateMachine(db_session, wind_down_grace=timedelta(seconds=900))
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="тест")
    return machine


async def test_db_row_is_written_before_broker_call(db_session, active_machine):
    """LLD §10 — «илгээгдсэн ч бүртгэгдээгүй» цонх үүсэхгүй."""
    seen: list[int] = []

    class Watching(FakeBroker):
        async def submit_order(self, req):
            rows = (await db_session.execute(select(models.Order))).scalars().all()
            seen.append(len(rows))
            return await FakeBroker.submit_order(self, req)

    agent = ExecutionAgent(db_session, Watching(), active_machine, mode="paper")
    await agent.submit(VALIDATED, origin=Origin.MANUAL_OPERATOR, origin_detail="operator")
    assert seen == [1]


async def test_successful_submit_records_broker_id_and_origin(db_session, active_machine):
    broker = FakeBroker()
    agent = ExecutionAgent(db_session, broker, active_machine, mode="paper")
    order = await agent.submit(
        VALIDATED, origin=Origin.RESEARCH_AGENT, origin_detail="claude-mcp/claude-opus-5"
    )
    assert order.broker_order_id == "alpaca-1"
    assert order.status == OrderStatus.ACCEPTED.value
    assert order.origin == "research_agent"
    assert order.origin_detail == "claude-mcp/claude-opus-5"
    assert order.mode == "paper"


async def test_broker_failure_marks_row_failed_not_lost(db_session, active_machine):
    agent = ExecutionAgent(
        db_session, FakeBroker(fail=BrokerUnavailable("нас барав")), active_machine, mode="paper"
    )
    with pytest.raises(BrokerUnavailable):
        await agent.submit(VALIDATED, origin=Origin.MANUAL_OPERATOR, origin_detail="operator")
    row = (await db_session.execute(select(models.Order))).scalar_one()
    assert row.status == OrderStatus.FAILED.value
    assert row.broker_order_id is None


async def test_state_is_rechecked_immediately_before_submit(db_session, active_machine):
    """TOCTOU — Risk-ийн шалгалтаас хойш kill switch дарагдсан байж болно."""
    await active_machine.transition(SystemState.HALTED, by="operator", reason="ЗОГСОО")
    broker = FakeBroker()
    agent = ExecutionAgent(db_session, broker, active_machine, mode="paper")
    with pytest.raises(BrokerUnavailable):
        await agent.submit(VALIDATED, origin=Origin.MANUAL_OPERATOR, origin_detail="operator")
    assert broker.submitted == []  # Alpaca руу 0 дуудалт
    row = (await db_session.execute(select(models.Order))).scalar_one()
    assert row.status == OrderStatus.FAILED.value
    assert row.failure_reason == "halted_before_submit"


async def test_validated_order_fields_are_not_mutated(db_session, active_machine):
    broker = FakeBroker()
    agent = ExecutionAgent(db_session, broker, active_machine, mode="paper")
    await agent.submit(VALIDATED, origin=Origin.MANUAL_OPERATOR, origin_detail="operator")
    sent = broker.submitted[0]
    assert sent == VALIDATED
    with pytest.raises((AttributeError, TypeError)):
        sent.qty = Decimal("999")  # frozen — Execution өөрчилж чадахгүй


async def test_audit_row_written_for_each_submit(db_session, active_machine):
    agent = ExecutionAgent(db_session, FakeBroker(), active_machine, mode="paper")
    await agent.submit(
        VALIDATED, origin=Origin.MANUAL_OPERATOR, origin_detail="operator", actor="operator"
    )
    rows = (
        (await db_session.execute(select(models.AuditLog).order_by(models.AuditLog.seq)))
        .scalars()
        .all()
    )
    assert rows[-1].event_type == "order_submitted"
    assert rows[-1].payload["origin"] == "manual_operator"
    assert rows[-1].payload["client_order_id"] == "p3-abc123"


async def test_idempotent_replay_returns_existing_row(db_session, active_machine):
    broker = FakeBroker()
    agent = ExecutionAgent(db_session, broker, active_machine, mode="paper")
    first = await agent.submit(VALIDATED, origin=Origin.MANUAL_OPERATOR, origin_detail="operator")
    second = await agent.submit(VALIDATED, origin=Origin.MANUAL_OPERATOR, origin_detail="operator")
    assert first.id == second.id
    assert len(broker.submitted) == 1  # давхар илгээлт БАЙХГҮЙ


async def test_manual_order_never_creates_agent_decision_row(db_session, active_machine):
    """AC-32 — гарын order нь agent-ийн шийдвэр БИШ."""
    agent = ExecutionAgent(db_session, FakeBroker(), active_machine, mode="paper")
    await agent.submit(VALIDATED, origin=Origin.MANUAL_OPERATOR, origin_detail="operator")
    decisions = (await db_session.execute(select(models.AgentDecision))).scalars().all()
    assert decisions == []


async def test_winding_down_does_not_block_execution_layer(db_session, active_machine):
    """Чиглэлийн шийдвэр нь Risk-ийнх. Execution нь зөвхөн `halted`-ыг барина."""
    await active_machine.transition(SystemState.WINDING_DOWN, by="operator", reason="унтраана")
    broker = FakeBroker()
    agent = ExecutionAgent(db_session, broker, active_machine, mode="paper")
    order = await agent.submit(
        replace(VALIDATED, side=OrderSide.SELL, client_order_id="p3-close"),
        origin=Origin.MANUAL_OPERATOR,
        origin_detail="operator",
    )
    assert order.status == OrderStatus.ACCEPTED.value
    assert len(broker.submitted) == 1
