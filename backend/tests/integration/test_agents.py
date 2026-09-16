"""T-18 (645) · T-19 (646) · T-20 (647) · T-21 (648) · T-22 (649) · T-48 (673).

Голууд:
- LLM-д нээлттэй бичих tool нь ЗӨВХӨН хоёр (INV-1).
- `propose_order` нь ORDER ИЛГЭЭХГҮЙ (Alpaca mock дуудалт = 0).
- `grounded_in`-гүй дуудалт схем дээр унана.
- tool result бүр `tool_call_id` + `system_state`-тай (INV-2, AC-34).
- Adapter-ийн орчуулсан схем нь ЭХ v1 схемтэй тэнцүү (round-trip).
- Hot-swap: restart БАЙХГҮЙ, нислэг дундах дуудалт хуучин provider-т.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import func, select

from app import models
from app.agents import contract
from app.agents.adapters.claude_mcp import ClaudeMcpAdapter
from app.agents.adapters.local_readonly import LocalReadOnlyAdapter
from app.agents.adapters.openai_fc import OpenAiFcAdapter, XaiFcAdapter
from app.agents.gateway import Gateway, StateView, ToolError, state_view
from app.agents.router import ProviderRouter, ProviderUnhealthy, UnknownProvider, default_router
from app.agents.tools import HANDLERS, ToolContext
from app.broker.models import Source, SystemState
from app.system.state import StateMachine
from tests.fakes import position, quote
from tests.helpers import activate, wind_down

SESSION_ID = "sess-test-1"


@pytest.fixture
async def machine(db_session, settings):
    m = StateMachine(db_session, wind_down_grace=settings.WIND_DOWN_GRACE)
    await m.ensure_initialised()
    await m.transition(SystemState.ACTIVE, by="operator", reason="тест")
    return m


@pytest.fixture
def tool_ctx(db_session, broker, settings, machine, bus):
    return ToolContext(
        session=db_session,
        broker=broker,
        settings=settings,
        machine=machine,
        bus=bus,
        provider_id="claude-mcp",
        model="claude-opus-5",
        session_id=SESSION_ID,
    )


@pytest.fixture
def gateway(db_session):
    return Gateway(
        db_session,
        HANDLERS,
        source=Source.ALPACA_PAPER,
        provider_id="claude-mcp",
        session_id=SESSION_ID,
    )


def rationale_args(**overrides) -> dict:
    base = {
        "symbol": "AAPL",
        "side": "buy",
        "qty": "10",
        "order_type": "limit",
        "limit_price": "221.50",
        "rationale": "Сүүлийн үнэ 221.50 дээр орох санал.",
        "grounded_in": [],
    }
    base.update(overrides)
    return base


async def cite_a_quote(gateway, tool_ctx, state, symbol="AAPL") -> str:
    """Бодит `get_quote` дуудалт хийж түүний `tool_call_id`-г буцаана."""
    result = await gateway.dispatch("get_quote", {"symbol": symbol}, state, tool_ctx)
    assert result["ok"], result
    return result["tool_call_id"]


@pytest.fixture
async def state(machine):
    return await state_view(machine)


# --- T-18: гэрээ ба гадаргуу ---


def test_only_two_write_tools_are_exposed():
    """INV-1 — LLM-д нээлттэй бичих шинжтэй tool нь хоёр."""
    write = [t["name"] for t in contract.tools() if t["access"] == "propose"]
    assert sorted(write) == ["propose_order", "propose_tuning_change"]


def test_read_only_providers_never_see_the_write_tools():
    """INV-5 — татгалзах биш, схемээс БҮРЭН хасагдана."""
    names = contract.tool_names(read_only=True)
    assert "propose_order" not in names
    assert "propose_tuning_change" not in names
    assert "get_quote" in names


def test_every_contract_tool_has_a_handler():
    assert set(contract.tool_names()) <= set(HANDLERS)


def test_every_input_schema_is_valid_json_schema():
    for name in contract.tool_names():
        Draft202012Validator.check_schema(contract.input_schema(name))


# --- T-48 / INV-2: result envelope ---


async def test_every_result_carries_id_timestamp_source_and_state(gateway, tool_ctx, state):
    result = await gateway.dispatch("get_account", {}, state, tool_ctx)
    for field in ("tool_call_id", "timestamp", "source", "system_state", "ok"):
        assert field in result, field
    assert result["timestamp"].endswith("Z")
    assert result["system_state"]["state"] == "active"
    assert result["system_state"]["guidance"]


async def test_the_result_envelope_matches_the_published_schema(gateway, tool_ctx, state):
    result = await gateway.dispatch("get_account", {}, state, tool_ctx)
    Draft202012Validator(contract.result_envelope_schema()).validate(result)


async def test_the_tool_call_is_persisted_before_the_answer_returns(
    gateway, tool_ctx, state, db_session
):
    """INV-4 — хариу LLM рүү буцахаас ӨМНӨ бичигдэнэ."""
    result = await gateway.dispatch("get_account", {}, state, tool_ctx)
    row = await db_session.get(models.ToolCall, uuid.UUID(result["tool_call_id"]))
    assert row is not None and row.response is not None
    assert row.provider == "claude-mcp"
    assert row.latency_ms is not None


async def test_state_change_shows_up_in_the_very_next_tool_result(
    gateway, tool_ctx, machine, db_session
):
    """AC-34 — agent төлөвийг мэдэлгүй үлдэх цонх БАЙХГҮЙ."""
    before = await gateway.dispatch("get_account", {}, await state_view(machine), tool_ctx)
    assert before["system_state"]["state"] == "active"

    await machine.transition(SystemState.WINDING_DOWN, by="operator", reason="унтраах")
    after = await gateway.dispatch("get_account", {}, await state_view(machine), tool_ctx)
    assert after["system_state"]["state"] == "winding_down"
    assert "reduce" in after["system_state"]["guidance"].lower()
    assert after["system_state"]["seconds_remaining"] is not None


async def test_a_missing_symbol_is_reported_not_guessed(gateway, tool_ctx, state):
    result = await gateway.dispatch("get_quote", {"symbol": "NOPE"}, state, tool_ctx)
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_symbol"
    assert result["data"] is None


async def test_a_schema_violation_is_refused(gateway, tool_ctx, state, broker):
    """`grounded_in`-гүй дуудалт схем дээр унана (T-18 DoD в)."""
    args = rationale_args()
    del args["grounded_in"]
    result = await gateway.dispatch("propose_order", args, state, tool_ctx)
    assert result["ok"] is False
    assert "grounded_in" in result["error"]["message"]
    assert broker.submitted == []


async def test_an_empty_grounded_in_is_refused(gateway, tool_ctx, state, broker):
    result = await gateway.dispatch("propose_order", rationale_args(), state, tool_ctx)
    assert result["ok"] is False
    assert broker.submitted == []


# --- propose_order: санал ≠ гүйцэтгэл ---


async def test_grounding_failure_stops_before_risk(gateway, tool_ctx, state, broker, db_session):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    citation = await cite_a_quote(gateway, tool_ctx, state)
    args = rationale_args(rationale="Үнэ 999.99 дээр", grounded_in=[citation])
    result = await gateway.dispatch("propose_order", args, state, tool_ctx)
    assert result["ok"]
    assert result["data"]["stage"] == "grounding_failed"
    assert result["data"]["unverified_claims"] == ["999.99"]
    assert broker.submitted == []
    row = (await db_session.execute(select(models.AgentDecision))).scalars().one()
    assert row.outcome == "grounding_failed"
    assert row.risk_evaluation is None  # Risk хүртэл ОЧООГҮЙ


async def test_a_fabricated_tool_call_id_fails_grounding(gateway, tool_ctx, state, broker):
    """Зөв тоо + буруу цитат: энэ санал тэр тоог ХАРААГҮЙ (T-24)."""
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    args = rationale_args(grounded_in=[str(uuid.uuid4())])
    result = await gateway.dispatch("propose_order", args, state, tool_ctx)
    assert result["data"]["stage"] == "grounding_failed"
    assert broker.submitted == []


async def test_a_grounded_approved_proposal_is_executed(gateway, tool_ctx, state, broker, db_session):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    citation = await cite_a_quote(gateway, tool_ctx, state)
    args = rationale_args(grounded_in=[citation])
    result = await gateway.dispatch("propose_order", args, state, tool_ctx)
    assert result["data"]["stage"] == "approved_for_execution"
    assert len(broker.submitted) == 1
    order = (await db_session.execute(select(models.Order))).scalars().one()
    assert order.origin == "research_agent"
    assert order.origin_detail == "claude-mcp/claude-opus-5"
    assert order.decision_id is not None


async def test_an_escalating_proposal_creates_an_approval_and_submits_nothing(
    gateway, tool_ctx, state, broker, db_session
):
    """AC-5 — approve хүртэл Alpaca руу 0 дуудалт."""
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    citation = await cite_a_quote(gateway, tool_ctx, state)
    args = rationale_args(qty="30", grounded_in=[citation])
    result = await gateway.dispatch("propose_order", args, state, tool_ctx)
    assert result["data"]["stage"] == "awaiting_approval"
    assert broker.submitted == []
    approval = (await db_session.execute(select(models.Approval))).scalars().one()
    assert approval.state == "pending"
    assert str(approval.id) == result["data"]["approval_id"]


async def test_a_risk_rejected_proposal_never_reaches_alpaca(
    gateway, tool_ctx, state, broker, db_session
):
    broker.quotes["GME"] = quote("GME", "20.00")
    citation = await cite_a_quote(gateway, tool_ctx, state, symbol="GME")
    args = rationale_args(
        symbol="GME", limit_price="20.00", rationale="Үнэ 20.00", grounded_in=[citation]
    )
    result = await gateway.dispatch("propose_order", args, state, tool_ctx)
    assert result["data"]["stage"] == "risk_rejected"
    assert broker.submitted == []


# --- T-48: төлөвийн эхний давхарга ---


async def test_halted_refuses_the_proposal_before_risk(
    gateway, tool_ctx, machine, broker, db_session
):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    citation = await cite_a_quote(gateway, tool_ctx, await state_view(machine))
    await machine.transition(SystemState.HALTED, by="operator", reason="зогсоов")
    result = await gateway.dispatch(
        "propose_order",
        rationale_args(grounded_in=[citation]),
        await state_view(machine),
        tool_ctx,
    )
    assert result["data"]["stage"] == "risk_rejected"
    assert "halted" in result["data"]["reason"]
    assert broker.submitted == []


async def test_winding_down_refuses_an_exposure_increase_with_a_usable_reason(
    gateway, tool_ctx, machine, broker
):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    citation = await cite_a_quote(gateway, tool_ctx, await state_view(machine))
    await machine.transition(SystemState.WINDING_DOWN, by="operator", reason="унтраах")
    result = await gateway.dispatch(
        "propose_order",
        rationale_args(grounded_in=[citation]),
        await state_view(machine),
        tool_ctx,
    )
    assert result["data"]["stage"] == "risk_rejected"
    # Agent засаж, ХААХ санал гаргаж чадахаар ойлгомжтой байх ёстой.
    assert "closing order" in result["data"]["reason"]
    assert broker.submitted == []


async def test_winding_down_still_accepts_a_closing_proposal(gateway, tool_ctx, machine, broker):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    broker.positions = [position("AAPL", "40", "8860.00")]
    citation = await cite_a_quote(gateway, tool_ctx, await state_view(machine))
    await machine.transition(SystemState.WINDING_DOWN, by="operator", reason="унтраах")
    result = await gateway.dispatch(
        "propose_order",
        rationale_args(side="sell", grounded_in=[citation]),
        await state_view(machine),
        tool_ctx,
    )
    assert result["data"]["stage"] == "approved_for_execution"
    assert len(broker.submitted) == 1


# --- propose_tuning_change ---


async def test_a_value_outside_the_bounds_is_refused(gateway, tool_ctx, state):
    result = await gateway.dispatch(
        "propose_tuning_change",
        {"parameter": "STOP_LOSS_PCT", "new_value": "9.9", "backtest_evidence": str(uuid.uuid4())},
        state,
        tool_ctx,
    )
    assert result["ok"] is False
    assert "мужаас гадуур" in result["error"]["message"]


async def test_an_unlisted_parameter_is_refused(gateway, tool_ctx, state):
    result = await gateway.dispatch(
        "propose_tuning_change",
        {"parameter": "MAX_ORDER_NOTIONAL", "new_value": "1", "backtest_evidence": str(uuid.uuid4())},
        state,
        tool_ctx,
    )
    assert result["ok"] is False
    assert "whitelist" in result["error"]["message"]


async def test_tuning_bounds_are_readable(gateway, tool_ctx, state):
    result = await gateway.dispatch("get_tuning_bounds", {}, state, tool_ctx)
    names = [p["name"] for p in result["data"]["parameters"]]
    assert "STOP_LOSS_PCT" in names


# --- T-19 / T-20 / T-22: adapter-ийн орчуулга ---


@pytest.mark.parametrize(
    "adapter,key",
    [
        (ClaudeMcpAdapter(), "inputSchema"),
        (LocalReadOnlyAdapter(), "input_schema"),
    ],
)
def test_adapter_schema_round_trips_against_the_source(adapter, key):
    translated = adapter.tool_schema()
    source = {t["name"]: t for t in adapter.source_tools()}
    assert [t["name"] for t in translated] == list(source)
    for entry in translated:
        assert entry[key] == source[entry["name"]]["input_schema"]
        assert entry["description"] == source[entry["name"]]["description"]


def test_openai_adapter_round_trips_against_the_source():
    adapter = OpenAiFcAdapter()
    source = {t["name"]: t for t in adapter.source_tools()}
    for entry in adapter.tool_schema():
        function = entry["function"]
        assert entry["type"] == "function"
        assert function["parameters"] == source[function["name"]]["input_schema"]
        assert function["description"] == source[function["name"]]["description"]
        assert function["strict"] is True


def test_the_local_adapter_hides_the_write_tools():
    names = [t["name"] for t in LocalReadOnlyAdapter().tool_schema()]
    assert "propose_order" not in names


def test_claude_tool_result_carries_the_envelope_unchanged():
    envelope = {"tool_call_id": "x", "ok": True, "data": {"last": "221.50"}}
    block = ClaudeMcpAdapter().tool_result_block("tu-1", envelope)
    import json

    assert json.loads(block["content"][0]["text"]) == envelope
    assert block["is_error"] is False


def test_openai_tool_result_carries_the_envelope_unchanged():
    envelope = {"tool_call_id": "x", "ok": False, "error": {"code": "no_data"}}
    message = OpenAiFcAdapter().tool_result_message("tc-1", envelope)
    import json

    assert json.loads(message["content"]) == envelope


def test_adapters_never_hold_credentials():
    """INV-4 — adapter-т key, DSN олгогдохгүй."""
    for adapter in (ClaudeMcpAdapter(), OpenAiFcAdapter(), LocalReadOnlyAdapter()):
        blob = repr(adapter.__dict__).lower()
        for needle in ("api_key", "secret", "password", "dsn", "postgres://"):
            assert needle not in blob


# --- T-21: Provider Router ---


def test_the_default_router_exposes_every_v1_provider():
    router = default_router(error_threshold=3)
    ids = [p["id"] for p in router.to_json()["providers"]]
    assert ids == ["claude-mcp", "openai-fc", "xai-fc", "local-fallback"]
    assert router.active_id("research") == "claude-mcp"


async def test_switching_only_reassigns_a_reference():
    """AC-10 — restart БАЙХГҮЙ: объектууд ижил хэвээр."""
    router = default_router(error_threshold=3)
    before = {k: id(v) for k, v in router.adapters.items()}
    await router.switch("research", "openai-fc")
    assert {k: id(v) for k, v in router.adapters.items()} == before
    assert router.active_id("research") == "openai-fc"


async def test_an_in_flight_session_keeps_its_old_adapter():
    """AC-11 — солих агшинд идэвхтэй байсан дуудлага хуучин provider-т."""
    router = default_router(error_threshold=3)
    bound = router.bind("research")
    await router.switch("research", "openai-fc")
    assert bound.spec.id == "claude-mcp"
    assert router.bind("research").spec.id == "openai-fc"


async def test_switching_to_an_unhealthy_provider_is_refused():
    router = default_router(error_threshold=1)
    router.get("openai-fc").record_error("timeout", threshold=1)
    with pytest.raises(ProviderUnhealthy):
        await router.switch("research", "openai-fc")
    assert router.active_id("research") == "claude-mcp"


async def test_switching_to_an_unknown_provider_is_refused():
    router = default_router(error_threshold=3)
    with pytest.raises(UnknownProvider):
        await router.switch("research", "does-not-exist")


def test_consecutive_errors_fall_back_to_the_read_only_provider():
    router = default_router(error_threshold=2)
    assert router.record_error("claude-mcp", "500") is None
    assert router.record_error("claude-mcp", "500") == "local-fallback"
    assert router.active_id("research") == "local-fallback"
    # Fallback нь read_only тул шинэ санал гарахгүй (LLD §12.3).
    assert router.any_writable() is False


def test_a_success_clears_the_error_streak():
    router = default_router(error_threshold=2)
    router.record_error("claude-mcp", "500")
    router.record_success("claude-mcp")
    assert router.record_error("claude-mcp", "500") is None
    assert router.active_id("research") == "claude-mcp"


# --- T-22: multi-provider scenario replay ---


async def test_the_same_scenario_yields_the_same_risk_decision_on_every_provider(
    db_session, broker, settings, machine, bus
):
    """Risk нь provider-ээс ХАМААРАХГҮЙ (AC-11). Хамаарвал тест унана."""
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    stages = []
    for provider_id, model in (("claude-mcp", "claude-opus-5"), ("openai-fc", "gpt-5")):
        session_id = f"sess-{provider_id}"
        ctx = ToolContext(
            session=db_session,
            broker=broker,
            settings=settings,
            machine=machine,
            bus=bus,
            provider_id=provider_id,
            model=model,
            session_id=session_id,
        )
        gw = Gateway(
            db_session,
            HANDLERS,
            source=Source.ALPACA_PAPER,
            provider_id=provider_id,
            session_id=session_id,
        )
        view = await state_view(machine)
        citation = await cite_a_quote(gw, ctx, view)
        out = await gw.dispatch(
            "propose_order", rationale_args(qty="30", grounded_in=[citation]), view, ctx
        )
        stages.append(out["data"]["stage"])
    assert stages[0] == stages[1] == "awaiting_approval"

    providers = {
        d.provider for d in (await db_session.execute(select(models.AgentDecision))).scalars()
    }
    assert providers == {"claude-mcp", "openai-fc"}


# --- REST гадаргуу ---


async def test_providers_endpoint_lists_active_role(client):
    body = (await client.get("/api/v1/providers")).json()
    assert body["active"]["research"] == "claude-mcp"
    assert any(p["read_only"] for p in body["providers"])


async def test_switch_endpoint_swaps_and_audits(client, db_session):
    response = await client.post(
        "/api/v1/providers/research/switch", json={"provider_id": "openai-fc"}
    )
    assert response.status_code == 200
    assert response.json()["new_provider_id"] == "openai-fc"
    rows = (
        await db_session.execute(
            select(models.AuditLog).where(models.AuditLog.event_type == "provider_switched")
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_switch_endpoint_refuses_an_unknown_provider(client):
    response = await client.post(
        "/api/v1/providers/research/switch", json={"provider_id": "nope"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "provider_unavailable"


async def test_decision_detail_returns_raw_tool_payloads(
    client, gateway, tool_ctx, state, broker, db_session
):
    """AC-8 — redaction-аас өөр засвар БАЙХГҮЙ."""
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    citation = await cite_a_quote(gateway, tool_ctx, state)
    await gateway.dispatch(
        "propose_order", rationale_args(grounded_in=[citation]), state, tool_ctx
    )
    decision = (await db_session.execute(select(models.AgentDecision))).scalars().one()

    body = (await client.get(f"/api/v1/agent-decisions/{decision.id}")).json()
    assert body["decision"]["provider"] == "claude-mcp"
    payloads = [c["response"] for c in body["tool_calls"]]
    assert any(p and p.get("data", {}).get("last") == "221.50" for p in payloads)


async def test_decision_list_filters_by_symbol(client, gateway, tool_ctx, state, broker):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    citation = await cite_a_quote(gateway, tool_ctx, state)
    await gateway.dispatch(
        "propose_order", rationale_args(grounded_in=[citation]), state, tool_ctx
    )
    hit = (await client.get("/api/v1/agent-decisions?symbol=AAPL")).json()["decisions"]
    miss = (await client.get("/api/v1/agent-decisions?symbol=TSLA")).json()["decisions"]
    assert len(hit) == 1 and miss == []


async def test_unknown_decision_is_404(client):
    assert (await client.get(f"/api/v1/agent-decisions/{uuid.uuid4()}")).status_code == 404
