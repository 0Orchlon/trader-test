"""Broker-ийн татгалзал нь tool-ийн ХАРИУ болно, цикл унагаахгүй."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import models
from app.agents.tools import ToolContext, propose_order
from app.broker.models import BrokerRejected, SystemState
from app.system.state import StateMachine
from tests.fakes import quote

ARGS = {
    "symbol": "AAPL",
    "side": "buy",
    "qty": "10",
    "order_type": "limit",
    "limit_price": "221.50",
    # Тоогүй үндэслэл — grounding-д шалгах зүйлгүй, цитат шаардахгүй.
    "rationale": "Чиг хандлага дээшээ байна.",
    "grounded_in": [],
}


@pytest.fixture
async def ctx(db_session, broker, settings, bus):
    machine = StateMachine(db_session, wind_down_grace=settings.WIND_DOWN_GRACE)
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="тест")
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    return ToolContext(
        session=db_session,
        broker=broker,
        settings=settings,
        machine=machine,
        bus=bus,
        provider_id="local-ollama",
        model="qwen3:4b-instruct",
        session_id="sess-order-failed",
    )


async def test_broker_rejection_is_reported_not_raised(ctx, broker, db_session):
    broker.fail_submit = BrokerRejected("wash trade", broker_code="40310000", status=422)

    result = await propose_order(ctx, ARGS)

    assert result["accepted"] is False
    assert result["stage"] == "order_failed"
    assert "wash trade" in result["reason"]
    decision = (await db_session.execute(select(models.AgentDecision))).scalars().one()
    assert decision.outcome == "order_failed"
    assert decision.order_id is None
