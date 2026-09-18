"""T-23 (650) provenance · T-25 (652) зөвхөн логоос сэргээх (AC-17, AC-18).

Скрипт нь `audit_log`-оос ӨӨР хүснэгтэд ХҮРЭХГҮЙ. Тест нь гаралтыг
`orders`/`agent_decisions`-тэй тулгаж бүрэн эсэхийг батална: лог өөрөө
бүрэн биш бол энэ тулгалт унана.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app import models
from app.audit.replay import KNOWN_EVENTS, replay_from_log
from app.audit.verifier import verify_chain
from app.broker.models import Source, SystemState
from app.agents.gateway import Gateway, state_view
from app.agents.tools import HANDLERS, ToolContext
from app.system.state import StateMachine
from tests.fakes import quote
from tests.helpers import activate

SESSION_ID = "sess-replay"


async def run_a_full_agent_trade(db_session, broker, settings, bus):
    """Нэг бүрэн урсгал: quote → grounded санал → APPROVE → submit."""
    machine = StateMachine(db_session, wind_down_grace=settings.WIND_DOWN_GRACE)
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="тест")
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
    view = await state_view(machine)
    citation = (await gateway.dispatch("get_quote", {"symbol": "AAPL"}, view, ctx))[
        "tool_call_id"
    ]
    await gateway.dispatch(
        "propose_order",
        {
            "symbol": "AAPL",
            "side": "buy",
            "qty": "10",
            "order_type": "limit",
            "limit_price": "221.50",
            "rationale": "Сүүлийн үнэ 221.50 дээр орох санал.",
            "grounded_in": [citation],
        },
        view,
        ctx,
    )
    return machine


async def test_the_decision_provenance_is_in_the_audit_log(db_session, broker, settings, bus):
    """T-23 — аль agent, аль provider/model, ямар өгөгдөл иш татсан."""
    await run_a_full_agent_trade(db_session, broker, settings, bus)
    row = (
        await db_session.execute(
            select(models.AuditLog).where(models.AuditLog.event_type == "agent_decision")
        )
    ).scalars().one()
    payload = row.payload
    assert row.actor == "agent:research"
    assert payload["provider"] == "claude-mcp" and payload["model"] == "claude-opus-5"
    assert payload["grounded_in"]
    assert payload["risk"]["decision"] == "APPROVE"
    assert payload["outcome"] == "executed"


async def test_the_chain_stays_intact_across_a_full_trade(db_session, broker, settings, bus):
    await run_a_full_agent_trade(db_session, broker, settings, bus)
    assert await verify_chain(db_session) is None


async def test_the_replay_reconstructs_the_order_from_the_log_alone(
    db_session, broker, settings, bus
):
    await run_a_full_agent_trade(db_session, broker, settings, bus)
    replay = await replay_from_log(db_session)

    order = (await db_session.execute(select(models.Order))).scalars().one()
    story = replay.orders[order.client_order_id]
    assert story.symbol == order.symbol
    assert story.side == order.side
    assert Decimal(story.qty) == order.qty
    assert story.origin == order.origin
    assert story.mode == order.mode
    assert story.broker_order_id == order.broker_order_id
    assert story.risk_decision == "APPROVE"


async def test_the_replay_links_the_order_back_to_its_rationale(
    db_session, broker, settings, bus
):
    """AC-18 — «ямар санал, ямар өгөгдлөөр үндэслэгдсэн»."""
    await run_a_full_agent_trade(db_session, broker, settings, bus)
    replay = await replay_from_log(db_session)
    story = next(iter(replay.orders.values()))
    decision = (await db_session.execute(select(models.AgentDecision))).scalars().one()

    assert story.decision_id == str(decision.id)
    assert story.rationale == decision.proposal["rationale"]
    assert story.grounded_in == decision.proposal["grounded_in"]
    assert story.provider == "claude-mcp" and story.model == "claude-opus-5"


async def test_the_replay_records_every_state_change(db_session, broker, settings, bus):
    machine = await run_a_full_agent_trade(db_session, broker, settings, bus)
    await machine.transition(SystemState.HALTED, by="operator", reason="дуусгав")
    replay = await replay_from_log(db_session)
    assert [c["to"] for c in replay.state_changes] == ["halted", "active", "halted"]


async def test_the_replay_captures_a_manual_order_with_its_operator(client, broker, db_session):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
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
    replay = await replay_from_log(db_session)
    story = next(iter(replay.orders.values()))
    assert story.origin == "manual_operator"
    # Гарын order нь agent-ийн санал БИШ — үндэслэл, цитат байхгүй (AC-32).
    assert story.rationale is None and story.grounded_in == []
    assert replay.decisions == []


async def test_the_replay_flags_unknown_event_types(db_session):
    from app.audit.chain import AuditChain

    await AuditChain(db_session).append("something_new", "system:test", {})
    await db_session.commit()
    replay = await replay_from_log(db_session)
    # Үл таних төрөл чимээгүй алдагдахгүй — ил гарна.
    assert replay.unknown_events == ["something_new"]


def test_every_event_this_system_writes_is_known_to_the_replay():
    """Шинэ үйл явдал нэмэхэд энэ тест сануулна."""
    import ast
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[2] / "app"
    written: set[str] = set()
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            is_append = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            )
            if is_append:
                written.add(node.args[0].value)
    assert written <= set(KNOWN_EVENTS), f"replay-д бүртгэгдээгүй: {written - set(KNOWN_EVENTS)}"
