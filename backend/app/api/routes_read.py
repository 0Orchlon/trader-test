"""Унших endpoint-ууд (T-07, T-46 · AC-1, AC-20, AC-21, AC-29, AC-30).

Энэ модуль Alpaca-ийн утга дээр ЮУ Ч нэмж тооцохгүй — зөвхөн буулгана.
`origin` нь локал `orders`-оос, `source` нь горимоос.
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app import models
from app.api.attribution import attribute, build_groups, position_origins
from app.api.deps import SessionDep, StateMachineDep
from app.api.envelope import envelope, money_field, qty_field
from app.api.problem import problem
from app.api.serializers import account_json, order_json, position_json
from app.broker.models import BrokerUnavailable, Source
from app.util.time import to_iso

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
    redis_ok = request.app.state.bus.redis is not None
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
                "detail": None if redis_ok else "тохируулаагүй",
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
