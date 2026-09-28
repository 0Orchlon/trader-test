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
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select

from app import models
from app.agents.gateway import Gateway, state_view
from app.agents.tools import (
    HANDLERS,
    STAGE_GROUNDING_FAILED,
    STAGE_RISK_REJECTED,
    ToolContext,
)
from app.api.attribution import _normalize
from app.broker.alpaca import is_crypto_symbol
from app.broker.models import BrokerUnavailable, SystemState
from app.config.mode import TradingMode
from app.system.state import StateMachine

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = (
    "You are the autonomous research agent for a personal PAPER trading account. "
    "You act ONLY through the tools you're given — there is no other way to affect "
    "the account. CRITICAL: deciding to trade means CALLING the propose_order "
    "tool/function — writing your decision as plain text does NOTHING, no order "
    "is placed, nobody sees it. Never describe a trade in prose instead of "
    "calling propose_order; if you've decided to trade, your response for that "
    "turn must be a propose_order tool call, not a sentence about one. Every "
    "cycle you are given a list of symbols to consider — you "
    "MUST call get_quote for EVERY symbol in that list, not just symbols you "
    "already hold a position in. Do not fixate on an existing position and skip "
    "the rest of the list — scan all of them, then decide. If one symbol's quote "
    "comes back stale or errors, do NOT abandon the whole cycle — just skip that "
    "one symbol (don't propose anything for it) and still decide on the rest. "
    "One bad symbol never blocks the others. Before proposing "
    "anything, check the account and current positions, and get a fresh quote "
    "for each symbol — that alone is enough to ground a decision. get_bars and "
    "get_news are OPTIONAL extra context, never required: if you're not 100% "
    "sure of get_bars' exact parameters, skip it rather than burn turns "
    "guessing — a decision grounded in just account+positions+quote is fine. "
    "Every numeric claim in a propose_order rationale must be grounded in a "
    "tool call you made THIS cycle — cite in grounded_in the tool_call_id you "
    "read the number from, or the proposal is rejected before anyone "
    "evaluates it. Do NOT write "
    "timestamps or dates in your rationale (e.g. '2026-09-18T20:45:22Z') — "
    "they get parsed as numeric claims and will almost never match exactly, "
    "failing your proposal for no real reason. Only state prices, quantities, "
    "and percentages; skip the clock. Prefer small, conservative trades — "
    "the goal is slow, steady growth, not big bets. You may be given both stock "
    "tickers (e.g. AAPL) and crypto pairs (format BASE/QUOTE, e.g. BTC/USD). "
    "Crypto trades 24/7 with no market hours; stocks only fill during market "
    "hours. Crypto orders must use time_in_force gtc or ioc — never day, Alpaca "
    "rejects that for crypto. Exits are NOT your job: a deterministic "
    "stop-loss / take-profit / max-hold rule closes every position "
    "automatically, without you. Focus on ENTRIES only — do not propose a sell "
    "to close a position you already hold, it collides with an exit that may "
    "already be in flight. If nothing looks worth doing this cycle, just stop "
    "without calling propose_order."
)


async def closed_trade_stats(session) -> dict[str, list[dict]]:
    """Хаагдсан арилжааны БОДИТ мөнгөн үр дүн. Prompt ба дэлгэц хоёр ЯГ
    энэ нэг функцээс уншина — тоо нь хэзээ ч зөрөхгүй.

    `realized_pl` бичигдсэн order бол хаалт (exit manager/ingest бичнэ);
    нээлтийн order-т `null` тул энд ОРОХГҮЙ.
    """
    rows = (
        await session.execute(
            select(
                models.Order.symbol,
                models.Order.side,
                # `realized_pl`-ийг ingest нь `filled_qty`-гээс тооцдог —
                # захиалсан `qty`-г хажууд нь хэвлэвэл хэсэгчлэн биелсэн
                # захиалгад тоо ба мөнгө нь ХАРИЛЦАН зөрнө (T-99).
                models.Order.filled_qty,
                models.Order.realized_pl,
                models.Order.origin_detail,
                models.Order.filled_at,
            )
            .where(models.Order.realized_pl.is_not(None))
            # `filled_at` хоосон мөр Postgres дээр DESC үед ТЭРГҮҮНД гарч
            # 20 мөрийн цонхыг эзэлдэг — тэднийг хамгийн ард нь тавина.
            .order_by(models.Order.filled_at.desc().nullslast())
            .limit(20)
        )
    ).all()
    per_symbol: dict[str, dict] = {}
    for row in rows:
        # `BTC/USD` ба `BTCUSD` нь НЭГ symbol — хоёр тусдаа түүх болгохгүй
        # (watchlist.py-тай ижил зарчим). Харуулах утга нь АНХНЫ БИЧЛЭГЭЭР
        # биш, `/`-тэй (order/quote-ийн канон хэлбэр) хэлбэрээр тогтмол
        # сонгогдоно — эс тэгвээс `filled_at DESC` дараалал өөрчлөгдөх
        # (өөр мөр хожим ирэх) бүрт ЯГ ЛУГ хоёр гэрээ өөр нэрээр харагдана.
        key = _normalize(row.symbol)
        stat = per_symbol.setdefault(
            key,
            {"symbol": row.symbol, "trades": 0, "wins": 0, "losses": 0, "net": Decimal("0")},
        )
        if "/" in row.symbol:
            stat["symbol"] = row.symbol
        stat["trades"] += 1
        if row.realized_pl > 0:
            stat["wins"] += 1
        elif row.realized_pl < 0:
            stat["losses"] += 1
        stat["net"] += row.realized_pl
    return {
        "per_symbol": list(per_symbol.values()),
        "recent": [
            {
                "symbol": row.symbol,
                "side": row.side,
                "qty": row.filled_qty,
                "realized_pl": row.realized_pl,
                "reason": (row.origin_detail or "manual").removeprefix("exit:"),
                "filled_at": row.filled_at,
            }
            for row in rows[:5]
        ],
    }


#: Prompt-ийн текст, үйл явдлын нэр БИШ — `test_replay` нь `.append("...")`-ийн
#: мөрийг үйл явдал гэж уншдаг тул нэрлэсэн тогтмолоор ялгав.
NO_CLOSED_TRADES = "No closed trades yet — no results to learn from."


def _money(value: Decimal) -> str:
    return f"{'-' if value < 0 else '+'}${abs(value):.2f}"


async def _learning_context(session) -> str:
    """Өмнөх мөчлөгүүдийн үр дүн prompt-д ЗӨВХӨН ЭНД, энгийн текстээр орно
    — tool result БИШ, тиймээс grounding-ийн citation болж чадахгүй.

    Шатны нэр («executed») мөнгө биш: +8% ба -8% арилжаа ижил мөр өгдөг
    байсан тул хаагдсан арилжааны доллараар сольсон. Хуучин зан төлөвөөс
    ганц мөр үлдэв: татгалзсан саналын тоо — citation зохиодог модельд
    энэ нь жинхэнэ ашигтай.
    """
    stats = await closed_trade_stats(session)
    blocks: list[str] = []
    if stats["per_symbol"]:
        blocks.append(
            "Your closed trades so far (real money, most recent 20):\n"
            + "\n".join(
                f"- {s['symbol']}: {s['trades']} trades, {s['wins']}W/{s['losses']}L, "
                f"net {_money(s['net'])}"
                for s in stats["per_symbol"]
            )
        )
        blocks.append(
            "Last closes:\n"
            + "\n".join(
                f"- {r['side']} {r['qty']} {r['symbol']} → {_money(r['realized_pl'])} "
                f"({r['reason']})"
                for r in stats["recent"]
            )
        )
    else:
        blocks.append(NO_CLOSED_TRADES)

    outcomes = (
        await session.execute(
            select(models.AgentDecision.outcome)
            .where(models.AgentDecision.agent == "research")
            .order_by(models.AgentDecision.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    rejected = sum(o in (STAGE_GROUNDING_FAILED, STAGE_RISK_REJECTED) for o in outcomes)
    if rejected:
        blocks.append(
            f"{rejected} of your last {len(outcomes)} proposals never reached the broker "
            "(grounding_failed / risk_rejected) — cite the tool_call_ids you really read "
            "and keep the size small."
        )
    return "\n\n".join(blocks)


async def _call_claude(settings, messages: list[dict], tools: list[dict]) -> dict[str, Any]:
    verify = settings.mode is not TradingMode.PAPER
    # T-99: local model inference (esp. thinking-mode models like qwen3) can
    # take well over a minute under load — 60s was too tight and produced a
    # silent httpx.ReadTimeout every cycle (T-99, хувийн төсөл).
    async with httpx.AsyncClient(timeout=180.0, verify=verify) as client:
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
    payload: dict[str, Any] = {
        "model": settings.LOCAL_MODEL_NAME,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        "tools": tools,
        # T-99: Ollama-ийн анхдагч num_ctx (2048-4096) нь олон эргэлттэй
        # tool-calling харилцан ярианд бага — цонх дүүрэхэд `400 Bad
        # Request` буцаадаг (эмпирик ажиглалт). Загвар өөрөө хавьгүй том
        # цонх дэмждэг тул харилцан ярианы урттай уялдуулж явцгаана.
        "options": {"num_ctx": 16384},
    }
    # T-99: local model inference (esp. thinking-mode models like qwen3) can
    # take well over a minute under load — 60s was too tight and produced a
    # silent httpx.ReadTimeout every cycle (T-99, хувийн төсөл).
    async with httpx.AsyncClient(timeout=180.0, verify=verify) as client:
        response = await client.post(settings.LOCAL_MODEL_URL, json=payload)
        response.raise_for_status()
        return response.json()


#: Жижиг local model (жишээ нь qwen3:4b) заримдаа `propose_order`-ийн ЗӨВ
#: бүтэцтэй JSON-ыг ЖИНХЭНЭ `tool_calls`-д БИШ, ердийн текстэнд бичдэг —
#: `tool_choice` АЛБАДСАН ч ялгаагүй (T-99, эмпирик ажиглалт, Ollama/
#: qwen3:4b-ийн хязгаарлалт). Энэ функц тэр текстийг сэргээж ЖИНХЭНЭ
#: dispatch-д зориулна — Risk/grounding хаалга бүрэн хэвээр ажиллана,
#: зөвхөн «tool дуудлага бодитоор үүсэхгүй» механик цоорхойг л засна.
_PROPOSE_ORDER_KEYS = {"symbol", "side", "qty", "order_type", "rationale"}
#: `symbol` дутуу байхад л ганц зөвшөөрөгдөх нөхцөл — бусад бүх талбар
#: заавал байх ёстой хэвээр (T-99, эмпирик ажиглалт).
_PROPOSE_ORDER_KEYS_SANS_SYMBOL = _PROPOSE_ORDER_KEYS - {"symbol"}


def _validate_propose_order_dict(
    data: Any, *, sole_held_symbol: str | None
) -> dict[str, Any] | None:
    # Заримдаа ганц объектоо жагсаалтад ораад бичдэг: `[{...}]` (T-99,
    # эмпирик ажиглалт) — зөвхөн ГАНЦ элементтэй үед л задална.
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        data = data[0]
    if not isinstance(data, dict):
        return None
    if _PROPOSE_ORDER_KEYS.issubset(data.keys()):
        return data
    # `symbol`-ыг «зөвхөн байгаа позиц» гэж ойлгож орхигдуулах нь ажиглагдсан
    # — ганц позиц байхад л, бусад талбар БҮГД байхад л тааж нөхнө.
    if (
        sole_held_symbol is not None
        and "symbol" not in data
        and _PROPOSE_ORDER_KEYS_SANS_SYMBOL.issubset(data.keys())
    ):
        return {**data, "symbol": sole_held_symbol}
    return None


def _find_json_objects(text: str) -> list[str]:
    """Текст дотроос хаалт ТЭНЦВЭРТЭЙ `{...}` дэд мөрүүдийг ол (T-99,
    эмпирик ажиглалт: заримдаа "Here's my order: {...}" гэх мэт зохиомол
    текстэнд ороож бичдэг). Утгыг ТААМАГЛАХГҮЙ — зөвхөн ХАЙЛТЫН байршлыг
    сулруулна, доор `_validate_propose_order_dict` хэвээрээ бүх шаардлагатай
    талбарыг НЭГ Ч ялгаагүй шалгана."""
    found: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            for j in range(i, len(text)):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        found.append(text[i : j + 1])
                        i = j
                        break
            else:
                break
        i += 1
    return found


def _extract_propose_order_json(content: str, *, sole_held_symbol: str | None = None) -> dict[str, Any] | None:
    text = content.strip().strip("`")
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        data = None
    if data is not None:
        result = _validate_propose_order_dict(data, sole_held_symbol=sole_held_symbol)
        if result is not None:
            return result
    # Шууд бүхэлдээ JSON биш байсан ч дотор нь ЯГ бүтэн `{...}` объект
    # байж болно ("Here's my order: {...}" гэх мэт) — байршлыг л сулруулна,
    # утгыг ХЭЗЭЭ Ч таамаглахгүй.
    for candidate in _find_json_objects(text):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        result = _validate_propose_order_dict(data, sole_held_symbol=sole_held_symbol)
        if result is not None:
            return result
    return None


def _resolve_held_symbol(raw_symbol: str, candidates: list[str]) -> str | None:
    """Позицийн raw symbol (`BTCUSD`, Alpaca-ийн `/v2/positions`-ээс, `/`-гүй)
    → тохиргооны symbol (`BTC/USD`, `/`-тэй) руу ЯГ нэг таарал олдвол л
    буцаана — олон/тэг таарал байвал `None` (T-99, эмпирик ажиглалт)."""
    matches = [c for c in candidates if c.replace("/", "") == raw_symbol.replace("/", "")]
    return matches[0] if len(matches) == 1 else None


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


def _read_key(name: str, symbol: Any) -> str:
    """`_reads`-ийн түлхүүр. Quote бүр symbol-оороо тусдаа — `BTC/USD` ба
    `BTCUSD` нэг л түлхүүр (`_normalize`)."""
    if name != "get_quote":
        return name
    return f"get_quote:{_normalize(str(symbol or '')).upper()}"


def _citations(reads: dict[str, str], symbol: Any) -> list[str]:
    """ЗӨВХӨН энэ саналд хамаатай citation: account + positions + тухайн
    symbol-ын quote. Уншсан БҮХ id-г цутгавал grounding нь «энэ тоо уншсан
    зүйлсийн хаа нэгтээ бий юу» болж мөхөс болно — өөр symbol-ын ask үнэ
    ч, buying_power ч аливаа мэдэгдлийг зөвтгөчихнө (T-99).

    Тухайн symbol-д quote аваагүй бол citation-д quote ОРОХГҮЙ — үнийн
    мэдэгдлийг grounding татгалзана, энэ нь ЗӨВ үр дүн.
    """
    keys = ("get_account", "get_positions", _read_key("get_quote", symbol))
    return [reads[k] for k in keys if k in reads]


async def _run_local_loop(gateway, ctx, machine, settings, opening: str, tools: list[dict]) -> None:
    """OpenAI-нийцтэй `/v1/chat/completions`-ийн `tool_calls` хэлбэрийн мөчлөг."""
    messages: list[dict] = [{"role": "user", "content": opening}]
    #: `propose_order`-ыг сэргээх үед ашиглах БОДИТ citation (модель бичсэн
    #: нэрс биш) — зөвхөн ЭНЭ session-д ЖИНХЭНЭ уншсан tool_call-уудын id,
    #: `_read_key`-ээр түлхүүрлэсэн.
    reads: dict[str, str] = {}
    #: Хамгийн сүүлд `get_positions`-ээс ирсэн raw symbol-ууд (`BTCUSD`) —
    #: `symbol`-гүй repair-ийн ганц зөвшөөрөгдөх контекст (доор).
    held_symbols: list[str] = []
    for _ in range(settings.RESEARCH_MAX_TOOL_TURNS):
        response = await _call_local(settings, messages, tools)
        choice = response["choices"][0]["message"]
        messages.append(choice)
        calls = choice.get("tool_calls") or []
        if not calls:
            sole_symbol = (
                _resolve_held_symbol(held_symbols[0], settings.research_symbols)
                if len(held_symbols) == 1
                else None
            )
            repaired = _extract_propose_order_json(
                choice.get("content") or "", sole_held_symbol=sole_symbol
            )
            if repaired is None:
                return
            repaired["grounded_in"] = _citations(reads, repaired.get("symbol"))
            state = await state_view(machine)
            await gateway.dispatch("propose_order", repaired, state, ctx)
            return
        state = await state_view(machine)
        for call in calls:
            raw_args = call["function"].get("arguments") or "{}"
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            if call["function"]["name"] == "propose_order":
                # Small local models reliably fabricate/mistype tool_call_id
                # UUIDs when citing them by hand — use the real IDs this
                # session actually read instead of trusting the transcription.
                args["grounded_in"] = _citations(reads, args.get("symbol"))
            name = call["function"]["name"]
            result = await gateway.dispatch(name, args, state, ctx)
            # АМЖИЛТГҮЙ уншилтаас ЮУ Ч санахгүй: алдаа/хуучирсан quote нь
            # citation болвол grounding тэр symbol-ын «нотолгоо» гэж
            # амжилтгүй payload-ыг үзнэ. Өмнөх амжилттай id нь хэвээр үлдэнэ.
            if result["ok"]:
                if name in ("get_account", "get_positions", "get_quote"):
                    reads[_read_key(name, args.get("symbol"))] = result["tool_call_id"]
                if name == "get_positions":
                    held_symbols = [p["symbol"] for p in result["data"]["positions"]]
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

    async with sessionmaker() as session:
        from app.agents.watchlist import get_active_symbols

        active_symbols = await get_active_symbols(session, settings)

        # Crypto 24/7 арилжаална тул watchlist дотор crypto pair байвал
        # энгийн зах зээлийн цагаар БҮХЭЛ мөчлөгийг алгасахгүй (T-99, хувийн
        # төсөл) — зөвхөн stock-ийн зах хаалттай, crypto ОГТ сонгоогүй үед
        # л зардал хэмнэхийн тулд алгасна.
        has_crypto = any(is_crypto_symbol(s) for s in active_symbols)
        if not has_crypto:
            try:
                clock = await broker.get_clock()
            except BrokerUnavailable:
                return
            if not clock.get("is_open", False):
                return

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
        symbols = ", ".join(active_symbols)
        opening = (
            f"{learning}\n\nSymbols to consider this cycle: {symbols}. "
            "Start by checking the account and current positions."
        )
        try:
            await call_loop(gateway, ctx, machine, settings, opening, tools)
        except httpx.HTTPError as exc:
            # `str(exc)` хоосон байж болно (жишээ нь ReadTimeout) — `repr`
            # ашиглана, эс тэгвэл алдаа ЧИМЭЭГҮЙ мэт харагдана (T-99).
            logger.warning("research cycle: %s call failed: %r", vendor, exc)
            provider_router.record_error(adapter.spec.id, str(exc))
            return
        provider_router.record_success(adapter.spec.id)
