"""T-37 (ID=664) — E2E сценарио harness (AC-2, AC-5, AC-9).

Бүрэн урсгал: Research санал → Risk хаалт → (approval) → Execution submit
→ Compliance лог → унших API-д тусгагдана.

Гурван салаа ТУС ТУСДАА: approve · reject · escalate. Нэг «аз таарсан»
замаар бүгдийг батлахгүй.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import models
from app.agents.gateway import Gateway, state_view
from app.agents.tools import HANDLERS, ToolContext
from app.audit.replay import replay_from_log
from app.audit.verifier import verify_chain
from app.broker.models import Source, SystemState
from app.system.state import StateMachine
from tests.fakes import quote
from tests.helpers import activate

SESSION_ID = "sess-e2e"


@pytest.fixture
async def research(db_session, broker, settings, bus):
    """Research agent-ийн session: gateway + context, идэвхтэй систем."""
    machine = StateMachine(db_session, wind_down_grace=settings.WIND_DOWN_GRACE)
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="e2e")
    broker.quotes["AAPL"] = quote("AAPL", "221.50")

    ctx = ToolContext(
        session=db_session,
        broker=broker,
        settings=settings,
        machine=machine,
        bus=bus,
        provider_id="claude-mcp",
        model="claude-opus-5",
        session_id=SESSION_ID,
    )
    gateway = Gateway(
        db_session,
        HANDLERS,
        source=Source.ALPACA_PAPER,
        provider_id="claude-mcp",
        session_id=SESSION_ID,
    )
    return gateway, ctx, machine


async def propose(research, **overrides):
    """Quote татаж, түүнийг иш татсан grounded санал гаргана."""
    gateway, ctx, machine = research
    view = await state_view(machine)
    citation = (await gateway.dispatch("get_quote", {"symbol": "AAPL"}, view, ctx))[
        "tool_call_id"
    ]
    args = {
        "symbol": "AAPL",
        "side": "buy",
        "qty": "10",
        "order_type": "limit",
        "limit_price": "221.50",
        "rationale": "Сүүлийн үнэ 221.50 дээр орох санал.",
        "grounded_in": [citation],
    }
    args.update(overrides)
    return await gateway.dispatch("propose_order", args, view, ctx), citation


# --- 1-р салаа: APPROVE → шууд гүйцэтгэл ---


async def test_approved_proposal_flows_all_the_way_to_the_read_api(
    research, client, broker, db_session
):
    result, citation = await propose(research)
    assert result["data"]["stage"] == "approved_for_execution"

    # Execution → Alpaca
    assert len(broker.submitted) == 1

    # Compliance: hash chain бүрэн, provenance бичигдсэн
    assert await verify_chain(db_session) is None
    replay = await replay_from_log(db_session)
    story = next(iter(replay.orders.values()))
    assert story.origin == "research_agent"
    assert citation in story.grounded_in

    # Dashboard-ийн унших зам дээр тусгагдсан
    orders = (await client.get("/api/v1/orders?status=all")).json()["orders"]
    assert [o["origin"] for o in orders] == ["research_agent"]
    assert orders[0]["origin_detail"] == "claude-mcp/claude-opus-5"

    # AC-9: цитат өгөгдөл UI-д харагдана
    detail = (await client.get(f"/api/v1/agent-decisions/{result['data']['decision_id']}")).json()
    payloads = [c["response"] for c in detail["tool_calls"]]
    assert any(p and p.get("data", {}).get("last") == "221.50" for p in payloads)


# --- 2-р салаа: ESCALATE → approve ---


async def test_escalated_proposal_waits_then_executes_on_approval(
    research, client, broker, db_session
):
    result, _ = await propose(research, qty="30")
    assert result["data"]["stage"] == "awaiting_approval"
    # AC-5: approve хүртэл Alpaca руу 0 дуудалт.
    assert broker.submitted == []

    listed = (await client.get("/api/v1/approvals")).json()["approvals"]
    assert len(listed) == 1
    row = listed[0]
    assert row["proposed_order"]["rationale"]
    assert row["risk"]["decision"] == "ESCALATE_TO_HUMAN"

    approved = await client.post(
        f"/api/v1/approvals/{row['id']}/approve", json={"expected_version": row["version"]}
    )
    assert approved.status_code == 202, approved.text
    assert len(broker.submitted) == 1
    assert approved.json()["order"]["origin"] == "research_agent"
    assert await verify_chain(db_session) is None


# --- 3-р салаа: ESCALATE → reject ---


async def test_rejected_proposal_is_never_sent(research, client, broker, db_session):
    result, _ = await propose(research, qty="30")
    row = (await client.get("/api/v1/approvals")).json()["approvals"][0]

    rejected = await client.post(
        f"/api/v1/approvals/{row['id']}/reject",
        json={"expected_version": row["version"], "reason": "Үндэслэл хангалтгүй"},
    )
    assert rejected.status_code == 200
    assert broker.submitted == []
    assert (await client.get("/api/v1/orders?status=all")).json()["orders"] == []

    replay = await replay_from_log(db_session)
    assert [a["resolution"] for a in replay.approvals if "resolution" in a] == ["rejected"]
    assert result["data"]["decision_id"]


# --- 4-р салаа: grounding унана → Risk хүртэл ОЧИХГҮЙ ---


async def test_an_ungrounded_proposal_stops_before_risk(research, broker, db_session):
    result, _ = await propose(research, rationale="Үнэ 999.99 болно.")
    assert result["data"]["stage"] == "grounding_failed"
    assert broker.submitted == []

    decision = (await db_session.execute(select(models.AgentDecision))).scalars().one()
    assert decision.risk_evaluation is None
    assert decision.grounding["unverified_claims"] == ["999.99"]


# --- WS: урсгалын мэдэгдэл (AC-2) ---


async def test_the_flow_publishes_to_the_decision_channel(research, bus):
    from app.stream.bus import CHANNEL_DECISIONS

    sub = bus.subscribe([CHANNEL_DECISIONS])
    await propose(research)
    events = [m.payload["event"] for m in sub.drain()]
    assert "decision_recorded" in events


async def test_a_manual_order_publishes_to_the_orders_channel(client, broker, bus):
    from app.stream.bus import CHANNEL_ORDERS

    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    sub = bus.subscribe([CHANNEL_ORDERS])
    await client.post(
        "/api/v1/orders/manual",
        json={
            "symbol": "AAPL",
            "side": "buy",
            "qty": "10",
            "order_type": "limit",
            "time_in_force": "day",
            "limit_price": "221.50",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert [m.payload["event"] for m in sub.drain()] == ["order_submitted"]
