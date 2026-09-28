"""Унших endpoint-ууд (T-07, T-46 · AC-1, AC-20, AC-21, AC-29, AC-30).

Энэ модуль Alpaca-ийн утга дээр ЮУ Ч нэмж тооцохгүй — зөвхөн буулгана.
`origin` нь локал `orders`-оос, `source` нь горимоос.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app import models
from app.agents.runner import closed_trade_stats
from app.api.attribution import _normalize, attribute, build_groups, position_origins
from app.api.deps import SessionDep, StateMachineDep
from app.api.envelope import envelope, money_field, qty_field
from app.api.problem import problem
from app.api.serializers import account_json, order_json, position_json
from app.broker.models import BrokerUnavailable, Source
from app.util.time import now_utc, to_iso

router = APIRouter()

OPEN_STATUSES = ("accepted", "partially_filled", "pending_approval", "pending_risk")
CLOSED_STATUSES = ("filled", "canceled", "expired", "rejected", "failed")


def current_source(request: Request) -> Source:
    """Горим → `source`. НЭГ эх функц (AC-20)."""
    return (
        Source.ALPACA_LIVE
        if request.app.state.settings.mode.value == "live"
        else Source.ALPACA_PAPER
    )


@router.get("/health", operation_id="getHealth")
async def get_health(request: Request, machine: StateMachineDep):
    state = await machine.current()
    broker_ok, detail = True, None
    try:
        await request.app.state.broker.get_account()
    except Exception as exc:  # broker унтарсан ч 200 — статусыг БИЕЭР нь заана
        broker_ok, detail = False, type(exc).__name__

    source = current_source(request)
    # «Тохируулсан» нь «хүрэх боломжтой» ГЭСЭН ҮГ БИШ — үнэхээр ping хийнэ.
    redis_ok, redis_detail = False, "тохируулаагүй"
    redis_client = request.app.state.bus.redis
    if redis_client is not None:
        try:
            await redis_client.ping()
            redis_ok, redis_detail = True, None
        except Exception as exc:
            redis_detail = type(exc).__name__
    provider_router = getattr(request.app.state, "provider_router", None)
    return envelope(
        {
            "status": "ok" if broker_ok else "degraded",
            "broker": {"name": source.value, "reachable": broker_ok, "detail": detail},
            "database": {"name": "postgres", "reachable": True},
            # Redis нь СОНГОЛТ (LLD §12): байхгүй нь доройтол, уналт биш.
            "redis": {
                "name": "redis",
                "reachable": redis_ok,
                "detail": redis_detail,
            },
            "providers": provider_router.health() if provider_router else [],
        },
        source=source,
        system_state=state.state,
    )


@router.get("/account", operation_id="getAccount")
async def get_account(request: Request, machine: StateMachineDep):
    try:
        result = await request.app.state.broker.get_account()
    except BrokerUnavailable as exc:
        raise problem("broker_unavailable", 503, str(exc)) from exc
    return envelope(
        {"account": account_json(result.data)},
        source=result.source,
        system_state=result.system_state,
        as_of=result.as_of,
        stale=result.stale,
    )


@router.get("/equity/history", operation_id="getEquityHistory")
async def get_equity_history(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    minutes: int = Query(240, ge=1, le=10080),
):
    """Минут тутмын БОДИТ түүвэр (T-99, хувийн төсөл, LLD-д тусгаагүй).

    `snapshot_equity` job-оос — интерполяци/тооцоолол БАЙХГҮЙ, зөвхөн
    Alpaca-ийн `equity`-ийн тухайн агшны утга.
    """
    since = now_utc() - timedelta(minutes=minutes)
    rows = (
        await session.execute(
            select(models.EquitySnapshot)
            .where(models.EquitySnapshot.ts >= since)
            .order_by(models.EquitySnapshot.ts)
        )
    ).scalars().all()
    state = await machine.current()
    return envelope(
        {
            "points": [
                {"ts": to_iso(row.ts), "equity": money_field(row.equity), "cash": money_field(row.cash)}
                for row in rows
            ]
        },
        source=current_source(request),
        system_state=state.state,
    )


@router.get("/positions", operation_id="getPositions")
async def get_positions(request: Request, machine: StateMachineDep, session: SessionDep):
    try:
        result = await request.app.state.broker.get_positions()
    except BrokerUnavailable as exc:
        raise problem("broker_unavailable", 503, str(exc)) from exc
    origins = await position_origins(session)
    return envelope(
        {"positions": [position_json(p, attribute(p, origins)) for p in result.data]},
        source=result.source,
        system_state=result.system_state,
        as_of=result.as_of,
        stale=result.stale,
    )


def _order_form_symbol(symbol: str, settings) -> str:
    """Alpaca-ийн `/v2/positions` нь crypto-с `/`-г хасдаг (`SOL/USD` ->
    `SOLUSD`) — `Position.symbol`-оор шууд quote/bars дуудвал Alpaca
    таньдаггүй, хоосон буцаана (T-99, эмпирик ажиглалт: candle chart
    хоосон харагдах шалтгаан). `exits.py`/`risk_context.py`-тэй ЯГ адилхан
    `settings.RESEARCH_SYMBOLS`-ийн slash-тэй бичлэг рүү буцаана."""
    watch = {_normalize(s): s for s in settings.research_symbols}
    return watch.get(_normalize(symbol), symbol)


@router.get("/market/quote/{symbol:path}", operation_id="getQuote")
async def get_quote(request: Request, machine: StateMachineDep, symbol: str):
    """Илгээхээс өмнөх notional-ийн эх сурвалж (LLD §16.5).

    Хуучирсан quote-ыг ЗАСАХГҮЙ, `stale` тугаар ил гаргана; quote огт
    байхгүй бол 503 — таамагласан үнэ буцаахгүй (хавсралт 10).
    """
    symbol = _order_form_symbol(symbol.upper(), request.app.state.settings)
    try:
        result = await request.app.state.broker.get_quote(symbol)
    except BrokerUnavailable as exc:
        raise problem("broker_unavailable", 503, str(exc)) from exc
    quote = result.data
    return envelope(
        {
            "quote": {
                "symbol": quote.symbol,
                "bid": money_field(quote.bid),
                "ask": money_field(quote.ask),
                "last": money_field(quote.last),
                "quote_ts": to_iso(quote.quote_ts),
            }
        },
        source=result.source,
        system_state=result.system_state,
        as_of=result.as_of,
        stale=result.stale,
    )


@router.get("/market/bars/{symbol:path}", operation_id="getMarketBars")
async def get_market_bars(
    request: Request,
    machine: StateMachineDep,
    symbol: str,
    timeframe: str = Query("5Min"),
    minutes: int = Query(240, ge=1, le=10080),
):
    """Candle chart-ийн эх сурвалж (T-99, хувийн төсөл, LLD-д тусгаагүй).

    `agents/tools.py::get_bars`-ийн ЯГ адилхан broker.get_bars-аар дамжина
    — байгаа bar-уудыг л буцаана, зохиосон bar ХЭЗЭЭ Ч биш.
    """
    broker = request.app.state.broker
    getter = getattr(broker, "get_bars", None)
    if getter is None:
        raise problem("broker_unavailable", 503, "энэ broker-т bars дэмжигдээгүй")
    symbol = _order_form_symbol(symbol.upper(), request.app.state.settings)
    end = now_utc()
    start = end - timedelta(minutes=minutes)
    try:
        bars = await getter(symbol, timeframe, to_iso(start), to_iso(end))
    except BrokerUnavailable as exc:
        raise problem("broker_unavailable", 503, str(exc)) from exc
    state = await machine.current()
    return envelope(
        {"symbol": symbol, "timeframe": timeframe, "bars": bars},
        source=current_source(request),
        system_state=state.state,
    )


@router.get("/orders", operation_id="getOrders")
async def get_orders(
    request: Request,
    machine: StateMachineDep,
    session: SessionDep,
    status: str = Query("open", pattern="^(open|closed|all)$"),
    symbol: str | None = None,
    origin: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    stmt = select(models.Order).order_by(models.Order.submitted_at.desc()).limit(limit)
    if status == "open":
        stmt = stmt.where(models.Order.status.in_(OPEN_STATUSES))
    elif status == "closed":
        stmt = stmt.where(models.Order.status.in_(CLOSED_STATUSES))
    if symbol:
        stmt = stmt.where(models.Order.symbol == symbol.upper())
    if origin:
        stmt = stmt.where(models.Order.origin == origin)
    rows = (await session.execute(stmt)).scalars().all()
    state = await machine.current()
    return envelope(
        {"orders": [order_json(row) for row in rows]},
        source=current_source(request),
        system_state=state.state,
    )


async def closed_trade_totals(session) -> tuple[int, Decimal]:
    """БҮХ хаалтын тоо ба цэвэр дүн — ХЯЗГААРГҮЙ.

    `closed_trade_stats` нь prompt-ийн цонх тул сүүлийн 20 мөрөөр таслагдана.
    Самбарын оноо тэр цонхоор гарвал 20 дээр хөшиж, дараагийн хаалт бүр нэгийг
    чимээгүй түлхэж гаргана. Онооны самбар нь бүх түүхээ харах ёстой.
    """
    row = (
        await session.execute(
            select(func.count(), func.sum(models.Order.realized_pl)).where(
                models.Order.realized_pl.is_not(None)
            )
        )
    ).one()
    return int(row[0]), Decimal(row[1] or 0)


@router.get("/performance", operation_id="getPerformance")
async def get_performance(request: Request, machine: StateMachineDep, session: SessionDep):
    """Хаагдсан арилжааны үр дүн (T-99, хувийн төсөл).

    `net`/`per_symbol`/`recent` нь prompt-ийн `_learning_context`-тэй ЯГ нэг
    эх функцээс — сүүлийн 20 хаалтын цонх. `total` нь тэр цонхгүй, бүх
    хаалтын нэгтгэл. Энд дахин нэгтгэл ХИЙХГҮЙ, зөвхөн буулгана.
    """
    stats = await closed_trade_stats(session)
    total_trades, total_net = await closed_trade_totals(session)
    state = await machine.current()
    return envelope(
        {
            "total": {"trades": total_trades, "net": money_field(total_net)},
            "per_symbol": [
                {
                    "symbol": s["symbol"],
                    "trades": s["trades"],
                    "wins": s["wins"],
                    "losses": s["losses"],
                    "net": money_field(s["net"]),
                }
                for s in stats["per_symbol"]
            ],
            "net": money_field(sum((s["net"] for s in stats["per_symbol"]), Decimal("0"))),
            "recent": [
                {
                    "symbol": r["symbol"],
                    "side": r["side"],
                    "qty": qty_field(r["qty"]),
                    "realized_pl": money_field(r["realized_pl"]),
                    "reason": r["reason"],
                    "filled_at": to_iso(r["filled_at"]),
                }
                for r in stats["recent"]
            ],
        },
        source=current_source(request),
        system_state=state.state,
    )


@router.get("/attribution", operation_id="getAttribution")
async def get_attribution(request: Request, machine: StateMachineDep, session: SessionDep):
    """FR-11 — «хэн юунд арилжаа хийж байна» (AC-30)."""
    try:
        result = await request.app.state.broker.get_positions()
    except BrokerUnavailable as exc:
        raise problem("broker_unavailable", 503, str(exc)) from exc
    groups = await build_groups(session, result.data)
    return envelope(
        {
            "groups": [
                {
                    "origin": origin.value,
                    "origin_detail": detail,
                    "symbols": [
                        {
                            "symbol": row.symbol,
                            "has_open_position": row.has_open_position,
                            "position_qty": qty_field(row.position_qty),
                            "market_value": money_field(row.market_value),
                            "open_order_count": row.open_order_count,
                            "origin_mixed": row.origin_mixed,
                            "last_decision_at": to_iso(row.last_decision_at),
                            "last_decision_id": row.last_decision_id,
                        }
                        for row in rows
                    ],
                }
                for origin, detail, rows in groups
            ]
        },
        source=result.source,
        system_state=result.system_state,
        as_of=result.as_of,
        stale=result.stale,
    )
