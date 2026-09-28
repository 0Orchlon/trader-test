"""Tool Contract v1-ийн handler-ууд (T-18, T-48, LLD §9.4, §12).

**LLM-д нээлттэй бичих шинжтэй tool нь ЗӨВХӨН `propose_order` ба
`propose_tuning_change`** (INV-1). Хоёул зөвхөн САНАЛ үүсгэнэ — Alpaca руу
ХЭЗЭЭ Ч шууд хүрэхгүй. `submit_order` энэ модульд дуудагдахгүй (статик
хаалга R-1): APPROVE-ийн салаа `ExecutionAgent`-ээр л явна.

`propose_order`-ийн дараалал (LLD §9.4):

1. `system_state` — `halted` бол Risk хүртэл ОЧИХГҮЙ; `winding_down` үед
   exposure нэмэгдүүлэх санал ил татгалзана (T-48). Энэ нь Risk-ийн R1/R2-ыг
   **ОРЛОХГҮЙ** — эхний давхарга, agent-т ойлгомжтой хариу өгөхийн тулд.
2. GroundingChecker — унавал `grounding_failed`, Risk хүртэл ОЧИХГҮЙ.
3. `risk.evaluate` → REJECT / ESCALATE (approvals мөр) / APPROVE (execution).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from app import models
from app.agents.gateway import ToolError
from app.agents.grounding import check as check_grounding
from app.api.attribution import EXTERNAL, _normalize as _normalize_symbol, position_origins
from app.audit.chain import AuditChain
from app.api.envelope import money_field, qty_field
from app.api.risk_context import build as build_risk_context
from app.approvals.queue import create_approval
from app.broker.alpaca import is_crypto_symbol
from app.broker.models import (
    BrokerRejected,
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
from app.risk.agent import evaluate
from app.risk.rules import increases_exposure, position_for
from app.stream.bus import CHANNEL_DECISIONS, CHANNEL_SYSTEM
from app.tuning.whitelist import bounds_json, lookup
from app.util.time import now_utc, to_iso

#: Crypto-д Alpaca зөвшөөрдөг ЦОРЫН ГАНЦ TIF-үүд. Бусад нь 422.
CRYPTO_TIF = frozenset({"gtc", "ioc"})

#: Тоон нотолгоо болж БОЛОХ tool-ууд (`grounded_in`-д иш татахад). `get_news`
#: ЭНД БАЙХГҮЙ: гарчиг дахь үнэ, нийтлэлийн id/цаг нь санамсаргүйгээр
#: rationale-ийн тоог «баталж» чадна — мэдээ бол чиглэл, нотолгоо биш.
NUMERIC_EVIDENCE_TOOLS = frozenset(
    {"get_account", "get_positions", "get_quote", "get_bars"}
)

STAGE_GROUNDING_FAILED = "grounding_failed"
STAGE_RISK_REJECTED = "risk_rejected"
STAGE_AWAITING_APPROVAL = "awaiting_approval"
STAGE_APPROVED = "approved_for_execution"
STAGE_ORDER_FAILED = "order_failed"

#: `agent_decisions.outcome` — contracts.yaml-ийн enum.
OUTCOME_FOR_STAGE = {
    STAGE_GROUNDING_FAILED: "grounding_failed",
    STAGE_RISK_REJECTED: "risk_rejected",
    STAGE_AWAITING_APPROVAL: "awaiting_approval",
    STAGE_APPROVED: "executed",
    STAGE_ORDER_FAILED: "order_failed",
}


@dataclass(slots=True)
class ToolContext:
    """Handler-ийн бүх хамаарал. Глобал БАЙХГҮЙ — тест шууд угсарна."""

    session: Any
    broker: Any
    settings: Any
    machine: Any
    bus: Any
    provider_id: str
    model: str
    session_id: str
    agent: str = "research"


# --- унших tool-ууд ---


async def get_account(ctx: ToolContext, args: dict) -> dict:
    try:
        account = (await ctx.broker.get_account()).data
    except BrokerUnavailable as exc:
        raise ToolError("unreachable", str(exc)) from exc
    return {
        "equity": money_field(account.equity),
        "cash": money_field(account.cash),
        "buying_power": money_field(account.buying_power),
        "day_trade_count": account.day_trade_count,
        "pattern_day_trader": account.pattern_day_trader,
    }


async def get_positions(ctx: ToolContext, args: dict) -> dict:
    try:
        positions = (await ctx.broker.get_positions()).data
    except BrokerUnavailable as exc:
        raise ToolError("unreachable", str(exc)) from exc
    origins = await position_origins(ctx.session)
    return {
        "positions": [
            {
                "symbol": p.symbol,
                "qty": qty_field(p.qty),
                "side": p.side.value,
                "avg_entry_price": money_field(p.avg_entry_price),
                "market_value": money_field(p.market_value),
                "origin": origins.get(p.symbol, EXTERNAL).origin.value,
            }
            for p in positions
        ]
    }


async def get_quote(ctx: ToolContext, args: dict) -> dict:
    """Таамагласан үнэ ХЭЗЭЭ Ч буцаахгүй. Байхгүйг ИЛ хэлнэ."""
    symbol = str(args["symbol"]).upper()
    try:
        result = await ctx.broker.get_quote(symbol)
    except BrokerUnavailable as exc:
        raise ToolError("invalid_symbol", f"{symbol}: {exc}") from exc
    if result.stale:
        raise ToolError("stale", f"{symbol}: quote {to_iso(result.as_of)}-аас хуучирсан")
    quote = result.data
    return {
        "symbol": quote.symbol,
        "bid": money_field(quote.bid),
        "ask": money_field(quote.ask),
        "last": money_field(quote.last),
        "quote_ts": to_iso(quote.quote_ts),
    }


async def get_bars(ctx: ToolContext, args: dict) -> dict:
    """Байгаа bar-уудыг л буцаана. Мужид өгөгдөл байхгүй бол `no_data` +
    ХООСОН массив — зохиосон bar ХЭЗЭЭ Ч биш (хавсралт 10)."""
    symbol = str(args["symbol"]).upper()
    getter = getattr(ctx.broker, "get_bars", None)
    if getter is None:
        raise ToolError("no_data", f"{symbol}: түүхэн өгөгдлийн эх сурвалж тохируулаагүй")
    try:
        bars = await getter(symbol, args["timeframe"], args["start"], args["end"])
    except BrokerUnavailable as exc:
        raise ToolError("unreachable", str(exc)) from exc
    if not bars:
        raise ToolError("no_data", f"{symbol}: {args['start']}…{args['end']} мужид bar байхгүй")
    return {"symbol": symbol, "timeframe": args["timeframe"], "bars": bars}


async def get_news(ctx: ToolContext, args: dict) -> dict:
    """Мэдээ — чиглэл өгөх контекст, `grounded_in`-д ХЭЗЭЭ Ч тоон нотолгоо
    болохгүй: `_cited_payloads` нь `NUMERIC_EVIDENCE_TOOLS`-оор шүүдэг тул
    энэ payload дахь тоо grounding-д ОГТ хүрэхгүй."""
    getter = getattr(ctx.broker, "get_news", None)
    if getter is None:
        raise ToolError("no_data", "мэдээний эх сурвалж тохируулаагүй")
    symbols = args.get("symbols")
    limit = int(args.get("limit", 10))
    try:
        news = await getter(symbols, limit)
    except BrokerUnavailable as exc:
        raise ToolError("unreachable", str(exc)) from exc
    if not news:
        raise ToolError("no_data", "тухайн симбол(ууд)-д мэдээ олдсонгүй")
    return {"news": news}


async def get_backtest_result(ctx: ToolContext, args: dict) -> dict:
    """`source` нь `backtest` — энэ өгөгдлийг live гэж ХЭЗЭЭ Ч тайлбарлахгүй."""
    runner = getattr(ctx, "backtester", None)
    if runner is None:
        raise ToolError("no_data", "backtest runner тохируулаагүй")
    return await runner(args)  # pragma: no cover - v1-д тохируулагдаагүй


async def get_tuning_bounds(ctx: ToolContext, args: dict) -> dict:
    """Whitelist + муж. API-аар ӨӨРЧЛӨХ endpoint БАЙХГҮЙ (T-26, AC-24)."""
    return {"parameters": bounds_json()}


# --- санал болгох tool-ууд (бичих шинжтэй, гэхдээ гүйцэтгэдэггүй) ---


def _decimal(value, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ToolError("no_data", f"{field}: тоон утга биш — {value!r}") from exc


def _same_symbol(value: Any, symbol: str) -> bool:
    # `BTC/USD` ба `BTCUSD` нь НЭГ symbol (attribution._normalize-тай ижил зарчим).
    return _normalize_symbol(str(value or "")).upper() == _normalize_symbol(symbol).upper()


def _mentions_other_symbol(node: Any, symbol: str) -> bool:
    """Бүтцийн ЯМАР Ч гүнд энэ саналынхаас ӨӨР symbol дурдагдсан эсэх.

    Зөвхөн дээд түвшний `symbol`/`positions`-ыг шалгавал дараагийн tool-ийн
    өөр бүтэц (жишээ нь `{"quotes": [...]}`) шүүлтээс чөлөөтэй өнгөрнө —
    яг тэр «өөр хаалга» гурван удаа давтагдсан.
    """
    if isinstance(node, dict):
        if "symbol" in node and not _same_symbol(node["symbol"], symbol):
            return True
        return any(_mentions_other_symbol(v, symbol) for v in node.values())
    if isinstance(node, list):
        return any(_mentions_other_symbol(v, symbol) for v in node)
    return False


def _narrowed(payload: Any, symbol: str) -> Any | None:
    """Цитат payload-оос ЭНЭ саналын symbol-д БАТЛАГДСАН хэсгийг л буцаана.

    Дүрэм нь ХААЛТТАЙ УНАНА: «өөр symbol-ынхыг хас» БИШ, «энэ symbol-ынх
    гэж батлагдсаныг л оруул». Тиймээс амжилтгүй дуудлага (`ok: false`,
    `data: null`), dict биш `data`, эсвэл дотроо өөр symbol дурдсан аливаа
    бүтэц `None` — нотолгоонд ОГТ орохгүй. Амжилтгүй tool call-д хууль ёсны
    тоон нотолгоо БАЙХГҮЙ (тэр хаалга `_cited_payloads`-д БАС бий: symbol
    дамжуулаагүй зам энэ функц хүртэл ирэхгүй).

    Зөвхөн `data` буцна: `error`-ийн мессеж, `tool_call_id` зэрэг бүрхүүлийн
    тоо (алдаанд бичигдсэн үнэ, uuid доторх орон) нотолгоо биш.

    Цитатыг ХЭН бүрдүүлснээс (модель гараар бичсэн ч, runner нөхсөн ч) үл
    хамааран энд шүүгдэнэ (T-99).
    """
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("positions"), list):
        data = {
            **data,
            "positions": [
                p
                for p in data["positions"]
                if isinstance(p, dict) and _same_symbol(p.get("symbol"), symbol)
            ],
        }
    # symbol-гүй бүтэц (`get_account`-ийн данс хэмжигдэхүүн) нь аль ч
    # symbol-д хамаарна — тэр нь ганц үлдэх өнгөрөх зам.
    return None if _mentions_other_symbol(data, symbol) else data


async def _cited_payloads(
    session,
    session_id: str,
    ids: list[str],
    allowed: frozenset[str] | None = None,
    symbol: str | None = None,
) -> tuple[list, list[str]]:
    """Цитат tool call-уудыг УНШИНА. Олдоогүй id нь ил алдаа.

    Зөв тоо + буруу `tool_call_id` нь хамгийн зальтай тохиолдол: тоо нь
    «байгаа» ч энэ санал түүнийг ХАРААГҮЙ. Тиймээс олдоогүй цитат нь
    grounding-ийг унагана (adversarial suite, T-24).

    `allowed` нь тоон нотолгоонд зөвшөөрөгдсөн tool-ийн нэрс. Бусад tool-ийн
    цитат нь АЛДАА биш (мэдээ иш татах нь зүйтэй), зүгээр л haystack-д
    ОРОХГҮЙ — иймд тэнд л байгаа тоо мэдэгдлийг батлахгүй.

    `symbol` өгвөл payload бүр `_narrowed`-ээр дамжина: энэ бол ГАДААД
    model аль ч замаар (Anthropic content block, local tool_calls) ирсэн
    цитатад ижилхэн үйлчилдэг цорын ганц газар.
    """
    found: list = []
    missing: list[str] = []
    for raw in ids:
        try:
            call_id = uuid.UUID(str(raw))
        except ValueError:
            missing.append(str(raw))
            continue
        row = await session.get(models.ToolCall, call_id)
        if row is None or row.session_id != session_id:
            missing.append(str(raw))
            continue
        if allowed is not None and row.tool_name not in allowed:
            continue
        payload = row.response
        # Амжилтгүй дуудлагын хаалга ЭНД — бүх зам дамждаг цорын ганц газар.
        # `_narrowed` дотор байхад `symbol`-гүй зам (`propose_tuning_change`)
        # түүнийг бүхэлд нь тойроод `{ok: false, data: null}` мөрийг
        # «нотолгоо» гэж тоолж байв (ROOT CAUSE F, өөр хаалга).
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            continue
        if symbol is not None:
            payload = _narrowed(payload, symbol)
        if payload is not None:
            found.append(payload)
    return found, missing


async def _record_decision(
    ctx: ToolContext,
    *,
    proposal: dict,
    grounding: dict,
    risk: dict | None,
    outcome: str,
    order_id: uuid.UUID | None = None,
) -> models.AgentDecision:
    row = models.AgentDecision(
        agent=ctx.agent,
        provider=ctx.provider_id,
        model=ctx.model,
        session_id=ctx.session_id,
        proposal=proposal,
        grounding=grounding,
        risk_evaluation=risk,
        outcome=outcome,
        order_id=order_id,
        created_at=now_utc(),
    )
    ctx.session.add(row)
    await ctx.session.flush()
    # Provenance нь audit_log-д БАС бичигдэнэ (T-23): аль agent, аль
    # provider/model, ямар өгөгдөл иш татсан, Risk юу шийдсэн. Ингэснээр
    # `app.audit.replay` нь ЗӨВХӨН логоос дарааллыг сэргээж чадна (AC-18).
    await AuditChain(ctx.session).append(
        "agent_decision",
        f"agent:{ctx.agent}",
        {
            "decision_id": str(row.id),
            "provider": ctx.provider_id,
            "model": ctx.model,
            "session_id": ctx.session_id,
            "symbol": proposal.get("symbol"),
            "side": proposal.get("side"),
            "qty": proposal.get("qty"),
            "rationale": proposal.get("rationale"),
            "grounded_in": proposal.get("grounded_in"),
            "grounding": grounding,
            "risk": risk,
            "outcome": outcome,
        },
    )
    await ctx.session.commit()
    if ctx.bus is not None:
        await ctx.bus.publish(
            CHANNEL_DECISIONS,
            # asyncapi `DecisionEvent` — аль agent, ямар model, ЯМАР өгөгдөл
            # дээр тулгуурласан нь ил (FR-10). `seq`/`ts`-ийг bus тамгална.
            {
                "event": "decision_recorded",
                "decision_id": str(row.id),
                "agent": ctx.agent,
                "provider": ctx.provider_id,
                "model": ctx.model,
                "symbol": proposal.get("symbol"),
                "outcome": outcome,
                "grounded_in": [str(x) for x in (proposal.get("grounded_in") or [])],
            },
        )
    return row


async def propose_order(ctx: ToolContext, args: dict) -> dict:
    """САНАЛ үүсгэнэ. ORDER ИЛГЭЭХГҮЙ (INV-1)."""
    symbol = str(args["symbol"]).upper()
    # Crypto-д Alpaca `day`-г 422-оор ТАТГАЛЗАНА. SYSTEM_PROMPT үүнийг том
    # үсгээр хэлдэг ч сул model үл тоомсорлож, татгалзлын хувь нь breaker-ийг
    # асаасан. Prompt бол хяналт биш — боломжгүй утгыг ЧИМЭЭГҮЙ засна.
    time_in_force = args.get("time_in_force", "day")
    if is_crypto_symbol(symbol) and time_in_force not in CRYPTO_TIF:
        time_in_force = "gtc"
    proposal = {
        "symbol": symbol,
        "side": args["side"],
        "qty": str(args["qty"]),
        "order_type": args["order_type"],
        "limit_price": args.get("limit_price"),
        "stop_price": args.get("stop_price"),
        "time_in_force": time_in_force,
        "rationale": args["rationale"],
        "grounded_in": list(args["grounded_in"]),
        "provider": ctx.provider_id,
        "model": ctx.model,
    }
    intent = OrderIntent(
        symbol=symbol,
        side=OrderSide(args["side"]),
        qty=_decimal(args["qty"], "qty"),
        order_type=OrderType(args["order_type"]),
        time_in_force=TimeInForce(time_in_force),
        limit_price=_decimal(args.get("limit_price"), "limit_price"),
        stop_price=_decimal(args.get("stop_price"), "stop_price"),
    )

    state = await ctx.machine.current()

    # 1) Төлөвийн эхний давхарга (T-48). Risk-ийн R1/R2 нь ХОЁР ДАХЬ давхарга
    #    хэвээр — энэ нь тэднийг ОРЛОХГҮЙ, зөвхөн agent-т эрт, ойлгомжтой
    #    хариу өгнө (LLD §12.4).
    if state.state is SystemState.HALTED:
        return await _rejected(
            ctx, proposal, reason="system halted — no proposal can be executed"
        )
    if state.state is SystemState.WINDING_DOWN:
        try:
            positions = (await ctx.broker.get_positions()).data
        except BrokerUnavailable as exc:
            raise ToolError("unreachable", str(exc)) from exc
        if increases_exposure(position_for(list(positions), symbol), intent):
            return await _rejected(
                ctx,
                proposal,
                reason=(
                    "system is winding down — only proposals that reduce or close an "
                    "existing position are accepted. Propose a closing order instead."
                ),
            )

    # 2) Grounding. Унавал Risk хүртэл ОЧИХГҮЙ (§13).
    payloads, missing = await _cited_payloads(
        ctx.session,
        ctx.session_id,
        proposal["grounded_in"],
        NUMERIC_EVIDENCE_TOOLS,
        symbol=symbol,
    )
    grounding = check_grounding(
        args["rationale"], payloads, tolerance=ctx.settings.GROUNDING_TOLERANCE
    )
    grounding_json = grounding.to_contract()
    if missing:
        grounding_json = {
            **grounding_json,
            "passed": False,
            "missing_tool_calls": missing,
            "unverified_claims": grounding_json["unverified_claims"]
            or [f"unknown tool_call_id: {m}" for m in missing],
        }
    if not grounding_json["passed"]:
        decision = await _record_decision(
            ctx,
            proposal=proposal,
            grounding=grounding_json,
            risk=None,
            outcome=OUTCOME_FOR_STAGE[STAGE_GROUNDING_FAILED],
        )
        return {
            "decision_id": str(decision.id),
            "accepted": False,
            "stage": STAGE_GROUNDING_FAILED,
            "reason": "every numeric claim must appear in a cited tool call payload",
            "unverified_claims": grounding_json["unverified_claims"],
        }

    # 3) Risk Agent.
    try:
        risk_ctx = await build_risk_context(
            ctx.broker,
            ctx.settings,
            state.state,
            symbol,
            idempotency_key=ctx.session_id,
            session=ctx.session,
        )
    except BrokerUnavailable as exc:
        raise ToolError("unreachable", str(exc)) from exc
    evaluation = evaluate(risk_ctx, intent)
    risk_json = evaluation.to_contract()

    if evaluation.decision is RiskDecision.REJECT:
        decision = await _record_decision(
            ctx,
            proposal=proposal,
            grounding=grounding_json,
            risk=risk_json,
            outcome=OUTCOME_FOR_STAGE[STAGE_RISK_REJECTED],
        )
        return {
            "decision_id": str(decision.id),
            "accepted": False,
            "stage": STAGE_RISK_REJECTED,
            "reason": evaluation.reason,
        }

    if evaluation.decision is RiskDecision.ESCALATE_TO_HUMAN:
        decision = await _record_decision(
            ctx,
            proposal=proposal,
            grounding=grounding_json,
            risk=risk_json,
            outcome=OUTCOME_FOR_STAGE[STAGE_AWAITING_APPROVAL],
        )
        approval = await create_approval(
            ctx.session,
            decision_id=decision.id,
            proposed_order=proposal,
            risk_evaluation=risk_json,
            ttl=ctx.settings.APPROVAL_TTL,
        )
        await ctx.session.commit()
        if ctx.bus is not None:
            # LLD §9.4 — operator-т мэдэгдэх ЦОРЫН ГАНЦ шуурхай зам.
            await ctx.bus.publish(
                CHANNEL_SYSTEM,
                {
                    "event": "approval_created",
                    "detail": {
                        "approval_id": str(approval.id),
                        "decision_id": str(decision.id),
                        "symbol": proposal.get("symbol"),
                        "expires_at": to_iso(approval.expires_at),
                    },
                },
            )
        return {
            "decision_id": str(decision.id),
            "accepted": False,
            "stage": STAGE_AWAITING_APPROVAL,
            "reason": evaluation.reason,
            "approval_id": str(approval.id),
        }

    # APPROVE — Execution руу. `submit_order` нь ТЭНД л дуудагдана.
    agent = ExecutionAgent(
        ctx.session, ctx.broker, ctx.machine, mode=ctx.settings.mode.value
    )
    decision = await _record_decision(
        ctx,
        proposal=proposal,
        grounding=grounding_json,
        risk=risk_json,
        outcome=OUTCOME_FOR_STAGE[STAGE_APPROVED],
    )
    try:
        order = await agent.submit(
            evaluation.validated_order,
            origin=Origin.RESEARCH_AGENT,
            origin_detail=f"{ctx.provider_id}/{ctx.model}",
            decision_id=decision.id,
            actor=f"agent:{ctx.agent}",
        )
    except (BrokerRejected, BrokerUnavailable) as exc:
        # Нэг татгалзал (wash trade, buying power) БҮХ scan-ыг унагаах ёсгүй —
        # энэ нь tool-ийн хариу, цикл цааш үргэлжилнэ.
        decision.outcome = OUTCOME_FOR_STAGE[STAGE_ORDER_FAILED]
        await ctx.session.commit()
        return {
            "decision_id": str(decision.id),
            "accepted": False,
            "stage": STAGE_ORDER_FAILED,
            "reason": str(exc),
        }
    decision.order_id = order.id
    await ctx.session.commit()
    return {
        "decision_id": str(decision.id),
        "accepted": True,
        "stage": STAGE_APPROVED,
        "reason": None,
        "order_id": str(order.id),
    }


async def _rejected(ctx: ToolContext, proposal: dict, *, reason: str) -> dict:
    decision = await _record_decision(
        ctx,
        proposal=proposal,
        # Grounding checker ОГТ ажиллаагүй (төлөвийн давхарга эрт татгалзав).
        # «passed: true» гэж бичвэл Decision Log нь шалгагдаагүйг шалгагдсан
        # мэт харуулна — хавсралт 10-ийн «мэдэхгүйг мэднэ болгохгүй» (N-3).
        grounding={
            "passed": False,
            "not_run": True,
            "unverified_claims": [],
            "checked_claims": 0,
        },
        risk=None,
        outcome=OUTCOME_FOR_STAGE[STAGE_RISK_REJECTED],
    )
    return {
        "decision_id": str(decision.id),
        "accepted": False,
        "stage": STAGE_RISK_REJECTED,
        "reason": reason,
    }


async def propose_tuning_change(ctx: ToolContext, args: dict) -> dict:
    """Муж дотор л санал. `applies_to` нь `paper` — `live` болох цорын ганц
    зам нь `POST /tuning/promote` + хүний баталгаажуулалт (AC-23)."""
    parameter = str(args["parameter"])
    spec = lookup(parameter)
    if spec is None:
        raise ToolError("no_data", f"{parameter}: whitelist-д байхгүй параметр")
    value = _decimal(args["new_value"], "new_value")
    if not spec.contains(value):
        raise ToolError(
            "no_data",
            f"{parameter}={value} нь батлагдсан мужаас гадуур "
            f"[{spec.minimum}, {spec.maximum}] step={spec.step}",
        )
    payloads, missing = await _cited_payloads(
        ctx.session, ctx.session_id, [args["backtest_evidence"]]
    )
    if missing or not payloads:
        raise ToolError(
            "no_data", "backtest_evidence нь АМЖИЛТТАЙ бодит tool call-д заагаагүй"
        )
    return {
        "parameter": parameter,
        "new_value": str(value),
        "applies_to": "paper",
        "accepted": True,
        "bounds": spec.to_json(),
    }


#: Gateway-д бүртгэгдэх ЦОРЫН ГАНЦ жагсаалт (T-18 DoD а).
HANDLERS = {
    "get_account": get_account,
    "get_positions": get_positions,
    "get_quote": get_quote,
    "get_bars": get_bars,
    "get_news": get_news,
    "get_backtest_result": get_backtest_result,
    "get_tuning_bounds": get_tuning_bounds,
    "propose_order": propose_order,
    "propose_tuning_change": propose_tuning_change,
}
