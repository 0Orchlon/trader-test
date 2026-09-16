"""Хөндлөн огтлолын төрлүүд — бүх давхаргын нийтлэг толь (LLD §4)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

Money = Decimal
Qty = Decimal
Instant = datetime


class Source(StrEnum):
    ALPACA_LIVE = "alpaca_live"
    ALPACA_PAPER = "alpaca_paper"
    BACKTEST = "backtest"


class SystemState(StrEnum):
    ACTIVE = "active"
    WINDING_DOWN = "winding_down"
    HALTED = "halted"


class Origin(StrEnum):
    RESEARCH_AGENT = "research_agent"
    AUTO_TUNING = "auto_tuning"
    MANUAL_OPERATOR = "manual_operator"
    EXTERNAL = "external"


class RiskDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    BRACKET = "bracket"


class TimeInForce(StrEnum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class OrderStatus(StrEnum):
    PENDING_RISK = "pending_risk"
    PENDING_APPROVAL = "pending_approval"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    EXPIRED = "expired"
    FAILED = "failed"


OPEN_ORDER_STATUSES = (
    OrderStatus.ACCEPTED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.PENDING_APPROVAL,
)


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    equity: Money
    cash: Money
    buying_power: Money
    pattern_day_trader: bool
    day_trade_count: int
    last_equity: Money | None = None
    trading_blocked: bool = False


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    qty: Qty
    side: PositionSide
    avg_entry_price: Money
    market_value: Money
    unrealized_pl: Money


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    bid: Money
    ask: Money
    last: Money
    quote_ts: Instant


@dataclass(frozen=True, slots=True)
class Tick:
    symbol: str
    price: Money
    ts: Instant


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    """Broker-ийн мэдээлсэн order. Локал тооцоо БАЙХГҮЙ (AC-1)."""

    broker_order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    qty: Qty
    filled_qty: Qty
    order_type: OrderType
    time_in_force: TimeInForce
    status: OrderStatus
    submitted_at: Instant
    filled_at: Instant | None = None
    limit_price: Money | None = None
    stop_price: Money | None = None


@dataclass(frozen=True, slots=True)
class TradeUpdate:
    event: str
    broker_order_id: str
    client_order_id: str
    status: OrderStatus
    filled_qty: Qty
    filled_avg_price: Money | None
    ts: Instant
    raw: dict


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Envelope(Generic[T]):
    """Өгөгдөлтэй хариу бүр `source` + `stale`-тай (AC-20, AC-21)."""

    data: T
    source: Source
    as_of: Instant
    stale: bool
    system_state: SystemState


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """Risk-ийн оролт. Хараахан баталгаажаагүй — ЭНЭ нь submit-д хүрэхгүй."""

    symbol: str
    side: OrderSide
    qty: Qty
    order_type: OrderType
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: Money | None = None
    stop_price: Money | None = None


@dataclass(frozen=True, slots=True)
class ValidatedOrder:
    """`risk.agent.evaluate()`-ийн APPROVE салаанаас л үүснэ (LLD §7, §8.1).

    Execution нь энэ талбаруудыг ӨӨРЧИЛЖ ЧАДАХГҮЙ — frozen.
    """

    symbol: str
    side: OrderSide
    qty: Qty
    order_type: OrderType
    time_in_force: TimeInForce
    limit_price: Money | None
    stop_price: Money | None
    client_order_id: str
    risk_evaluation: dict = field(default_factory=dict)


class BrokerUnavailable(RuntimeError):
    """Alpaca хүрэхгүй. Кэшээс хуучин утга буцаах зам БАЙХГҮЙ (LLD §7)."""


__all__ = [n for n in dir() if not n.startswith("_")]
