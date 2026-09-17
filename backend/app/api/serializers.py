"""Домэйн → contracts.yaml-ийн JSON (T-07).

Serializer бүр `envelope.money_field` / `qty_field`-ээр дамжина: float нь
хилийн дээр л баригдана, гүн рүү орохгүй.
"""
from __future__ import annotations

from typing import Any

from app import models
from app.api.attribution import Attribution
from app.api.envelope import money_field, qty_field
from app.broker.models import Account, BrokerOrder, Position
from app.util.time import to_iso


def account_json(account: Account) -> dict[str, Any]:
    return {
        "account_id": account.account_id,
        "equity": money_field(account.equity),
        "cash": money_field(account.cash),
        "buying_power": money_field(account.buying_power),
        "last_equity": money_field(account.last_equity),
        "pattern_day_trader": account.pattern_day_trader,
        "day_trade_count": account.day_trade_count,
        "trading_blocked": account.trading_blocked,
    }


def position_json(position: Position, attribution: Attribution) -> dict[str, Any]:
    return {
        "symbol": position.symbol,
        "qty": qty_field(position.qty),
        "side": position.side.value,
        "avg_entry_price": money_field(position.avg_entry_price),
        "market_value": money_field(position.market_value),
        "unrealized_pl": money_field(position.unrealized_pl),
        "origin": attribution.origin.value,
        "origin_detail": attribution.origin_detail,
        # Холимог origin-ийг ДАЛДЛАХГҮЙ (LLD §11.1 хязгаарлалт).
        "origin_mixed": attribution.mixed,
    }


def order_json(order: models.Order) -> dict[str, Any]:
    return {
        "id": str(order.id),
        "broker_order_id": order.broker_order_id,
        "client_order_id": order.client_order_id,
        "symbol": order.symbol,
        "side": order.side,
        "qty": qty_field(order.qty),
        "filled_qty": qty_field(order.filled_qty),
        "order_type": order.order_type,
        "limit_price": money_field(order.limit_price),
        "stop_price": money_field(order.stop_price),
        "time_in_force": order.time_in_force,
        "status": order.status,
        "origin": order.origin,
        "origin_detail": order.origin_detail,
        "decision_id": str(order.decision_id) if order.decision_id else None,
        "submitted_at": to_iso(order.submitted_at),
        "filled_at": to_iso(order.filled_at),
    }


def order_event(event: str, order: models.Order, *, source) -> dict[str, Any]:
    """asyncapi `OrderUpdate` — шаардлагатай талбарууд ДЭЭД ТҮВШИНД (B-2).

    Order-ийн нийтлэл гурван замаас гардаг (гарын order, approval, trade
    update). Хэлбэрийг зам тус бүрд бичих нь нэг сувагт гурван өөр гэрээ
    болно — тиймээс НЭГ угсрагч. `seq`/`ts`-ийг bus тамгална.
    """
    return {
        "event": event,
        "order_id": str(order.id),
        "broker_order_id": order.broker_order_id,
        "symbol": order.symbol,
        "status": order.status,
        "filled_qty": qty_field(order.filled_qty),
        "origin": order.origin,
        "origin_detail": order.origin_detail,
        "source": getattr(source, "value", source),
        # Бүтэн мөр нь UI-д хэрэгтэй; гэрээ нэмэлт талбарыг хориглоогүй.
        "order": order_json(order),
    }


def broker_order_json(order: BrokerOrder) -> dict[str, Any]:
    """Alpaca-аас ирсэн, локал мөргүй order (reconciliation-д)."""
    return {
        "broker_order_id": order.broker_order_id,
        "client_order_id": order.client_order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "qty": qty_field(order.qty),
        "filled_qty": qty_field(order.filled_qty),
        "order_type": order.order_type.value,
        "time_in_force": order.time_in_force.value,
        "status": order.status.value,
        "submitted_at": to_iso(order.submitted_at),
        "filled_at": to_iso(order.filled_at),
    }


def approval_json(approval: models.Approval) -> dict[str, Any]:
    return {
        "id": str(approval.id),
        "version": approval.version,
        "state": approval.state,
        "decision_id": str(approval.decision_id) if approval.decision_id else None,
        "proposed_order": approval.proposed_order,
        "risk": approval.risk_evaluation,
        "created_at": to_iso(approval.created_at),
        "expires_at": to_iso(approval.expires_at),
        "resolved_at": to_iso(approval.resolved_at),
        "resolution_reason": approval.resolution_reason,
    }


def decision_json(decision: models.AgentDecision) -> dict[str, Any]:
    return {
        "id": str(decision.id),
        "agent": decision.agent,
        "provider": decision.provider,
        "model": decision.model,
        "created_at": to_iso(decision.created_at),
        "proposal": decision.proposal,
        "risk": decision.risk_evaluation,
        "grounding": decision.grounding,
        "outcome": decision.outcome,
        "order_id": str(decision.order_id) if decision.order_id else None,
    }


def tool_call_json(call: models.ToolCall) -> dict[str, Any]:
    """AC-9 — ТҮҮХИЙ payload. Redaction-аас өөр засвар БАЙХГҮЙ."""
    return {
        "id": str(call.id),
        "tool_name": call.tool_name,
        "request": call.request,
        "response": call.response,
        "source": call.source,
        "called_at": to_iso(call.called_at),
        "latency_ms": call.latency_ms,
    }
