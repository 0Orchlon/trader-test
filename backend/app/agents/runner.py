"""Autonomous research cycle — гадаад LLM дуудлага (T-99, хувийн төсөл).

LLD-д ТУСГААГҮЙ: энэ бол хувийн (компанийн бус) төслийн нэмэлт, "zero
human input" горимд зориулагдсан. Бүх шийдвэрийн логик (grounding, Risk
Agent, execution) `agents/tools.py` + `agents/gateway.py`-д аль хэдийн
бий — энэ модуль ЗӨВХӨН гадаад LLM-тэй ярилцаж, түүний хүссэн tool
дуудлага бүрийг Gateway-ээр (өөрөөр хэлбэл ЯГ адилхан risk/audit
хаалгаар) дамжуулна. `submit_order`-д ХҮРЭХ цорын ганц зам хэвээрээ
`propose_order` → `ExecutionAgent` — энд шинэ зам НЭЭГДЭХГҮЙ.

Хоёр "тархи": Claude (Anthropic Messages API, шууд дуудалт) ба local
model (OpenAI-нийцтэй `/v1/chat/completions`). Аль нэг нь идэвхтэй ба
тохируулагдсан бол л мөчлөг ажиллана; аль аль нь тохируулаагүй бол
чимээгүй алгасна (эвдрэл БИШ).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select

from app import models
from app.agents.gateway import Gateway, state_view
from app.agents.tools import HANDLERS, ToolContext
from app.broker.models import BrokerUnavailable, SystemState
from app.config.mode import TradingMode
from app.system.state import StateMachine

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = (
    "You are the autonomous research agent for a personal PAPER trading account. "
    "You act ONLY through the tools you're given — there is no other way to affect "
    "the account. Before proposing anything, check the account and current "
    "positions and get a fresh quote for any symbol you're considering. Every "
    "numeric claim in a propose_order rationale must be grounded in a tool call "
    "you made this cycle (cite its tool_call_id in grounded_in) or the proposal "
    "is rejected before anyone evaluates it. Prefer small, conservative trades — "
    "the goal is slow, steady growth, not big bets. If nothing looks worth doing "
    "this cycle, just stop without calling propose_order."
)


async def _learning_context(session) -> str:
    """Сүүлийн шийдвэрийн үр дүн — "сургалт" гэдгийг ЭНЭ мөчлөгт ингэж
    хэрэгжүүлсэн: жинхэнэ backtest/walk-forward биш (`tuning/promote.py`
    үүнийг шаарддаг ч `get_backtest_result` unwired), зүгээр л сүүлийн
    үр дүнгээ дараагийн prompt-д харуулж, LLM-ийг in-context тохируулна.
    """
    rows = (
        await session.execute(
            select(models.AgentDecision)
            .where(models.AgentDecision.agent == "research")
            .order_by(models.AgentDecision.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    if not rows:
        return "No prior decisions yet — this is the first cycle."
    lines = [
        f"- {row.created_at.isoformat()} {(row.proposal or {}).get('side', '?')} "
        f"{(row.proposal or {}).get('symbol', '?')}: {row.outcome}"
        for row in rows
    ]
    return "Your last decisions (most recent first):\n" + "\n".join(lines)


async def _call_claude(settings, messages: list[dict], tools: list[dict]) -> dict[str, Any]:
    verify = settings.mode is not TradingMode.PAPER
    async with httpx.AsyncClient(timeout=60.0, verify=verify) as client:
        response = await client.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": settings.CLAUDE_MODEL,
                "max_tokens": 2048,
                "system": SYSTEM_PROMPT,
                "messages": messages,
                "tools": tools,
            },
        )
        response.raise_for_status()
        return response.json()


async def _call_local(settings, messages: list[dict], tools: list[dict]) -> dict[str, Any]:
    verify = settings.mode is not TradingMode.PAPER
    async with httpx.AsyncClient(timeout=60.0, verify=verify) as client:
        response = await client.post(
            settings.LOCAL_MODEL_URL,
            json={
                "model": settings.LOCAL_MODEL_NAME,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
                "tools": tools,
            },
        )
        response.raise_for_status()
        return response.json()


async def _run_claude_loop(gateway, ctx, machine, settings, opening: str, tools: list[dict]) -> None:
    """Anthropic Messages API-ийн `content`-блок хэлбэрийн tool-use мөчлөг."""
    messages: list[dict] = [{"role": "user", "content": opening}]
    for _ in range(settings.RESEARCH_MAX_TOOL_TURNS):
        response = await _call_claude(settings, messages, tools)
        content = response.get("content", [])
        messages.append({"role": "assistant", "content": content})
        tool_uses = [block for block in content if block.get("type") == "tool_use"]
        if not tool_uses:
            return
        state = await state_view(machine)
        results = []
        for block in tool_uses:
            result = await gateway.dispatch(block["name"], block.get("input") or {}, state, ctx)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "is_error": not result["ok"],
                }
            )
        messages.append({"role": "user", "content": results})
        if response.get("stop_reason") != "tool_use":
            return


async def _run_local_loop(gateway, ctx, machine, settings, opening: str, tools: list[dict]) -> None:
    """OpenAI-нийцтэй `/v1/chat/completions`-ийн `tool_calls` хэлбэрийн мөчлөг."""
    messages: list[dict] = [{"role": "user", "content": opening}]
    for _ in range(settings.RESEARCH_MAX_TOOL_TURNS):
        response = await _call_local(settings, messages, tools)
        choice = response["choices"][0]["message"]
        messages.append(choice)
        calls = choice.get("tool_calls") or []
        if not calls:
            return
        state = await state_view(machine)
        for call in calls:
            raw_args = call["function"].get("arguments") or "{}"
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            result = await gateway.dispatch(call["function"]["name"], args, state, ctx)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )


async def run_research_cycle(sessionmaker, settings, broker, publisher, provider_router, bus) -> None:
    """APScheduler-ийн job. Тохиргоо дутуу/зах хаалттай/broker унасан бол
    ЧИМЭЭГҮЙ алгасна — энэ job хэзээ ч scheduler-ийг унагахгүй ёстой."""
    adapter = provider_router.bind("research")
    if adapter is None or not adapter.healthy or adapter.spec.read_only:
        return
    vendor = adapter.spec.vendor
    if vendor == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            return
        call_loop = _run_claude_loop
        tools = adapter.to_anthropic_tools()
    elif vendor == "local":
        if not settings.LOCAL_MODEL_URL:
            return
        call_loop = _run_local_loop
        tools = adapter.tool_schema()
    else:
        # OpenAI/xAI: schema-орчуулагчид бэлэн ч ЭНД гадагш дуудалт хараахан
        # тохируулаагүй (API key/URL байхгүй) — чимээгүй алгасна.
        return

    try:
        clock = await broker.get_clock()
    except BrokerUnavailable:
        return
    if not clock.get("is_open", False):
        return

    async with sessionmaker() as session:
        machine = StateMachine(session, wind_down_grace=settings.WIND_DOWN_GRACE, publisher=publisher)
        state = await machine.current()
        if state.state is not SystemState.ACTIVE or not provider_router.any_writable():
            return

        session_id = str(uuid.uuid4())
        ctx = ToolContext(
            session=session,
            broker=broker,
            settings=settings,
            machine=machine,
            bus=bus,
            provider_id=adapter.spec.id,
            model=adapter.spec.model,
            session_id=session_id,
        )
        gateway = Gateway(
            session,
            HANDLERS,
            source=broker.source,
            provider_id=adapter.spec.id,
            session_id=session_id,
            read_only=adapter.spec.read_only,
        )
        learning = await _learning_context(session)
        symbols = ", ".join(settings.research_symbols)
        opening = (
            f"{learning}\n\nSymbols to consider this cycle: {symbols}. "
            "Start by checking the account and current positions."
        )
        try:
            await call_loop(gateway, ctx, machine, settings, opening, tools)
        except httpx.HTTPError as exc:
            logger.warning("research cycle: %s call failed: %s", vendor, exc)
            provider_router.record_error(adapter.spec.id, str(exc))
            return
        provider_router.record_success(adapter.spec.id)
