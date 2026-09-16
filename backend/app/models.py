"""ORM хүснэгтүүд — LLD §5-ийн 10 хүснэгт.

Багануудын жагсаалт нь **хамгийн бага хангалттай** олонлог. Дутуу талбар нэмэх
нь шинэ шийдвэр — LLD-д буцаж бичигдэнэ.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime

NUM = Numeric(20, 8)
#: SQLite-д BIGINT нь autoincrement хийдэггүй — variant-аар INTEGER болгоно.
SEQ = BigInteger().with_variant(Integer, "sqlite")
TS = UtcDateTime()


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    broker_account_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    #: Secrets manager-ийн ЛАВЛАГАА. Түлхүүр өөрөө ХЭЗЭЭ Ч энд орохгүй (NFR-3).
    key_ref: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (CheckConstraint("mode in ('paper','live')", name="ck_accounts_mode"),)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    client_order_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    broker_order_id: Mapped[str | None] = mapped_column(Text, unique=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid, ForeignKey("accounts.id"))
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    filled_qty: Mapped[Decimal] = mapped_column(NUM, nullable=False, default=Decimal("0"))
    order_type: Mapped[str] = mapped_column(Text, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(NUM)
    stop_price: Mapped[Decimal | None] = mapped_column(NUM)
    time_in_force: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    #: AC-29 — анхдагч утга БАЙХГҮЙ. Дуудагч бүр ил заана.
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    origin_detail: Mapped[str | None] = mapped_column(Text)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid)
    risk_evaluation: Mapped[dict] = mapped_column(JSON, nullable=False)
    #: Мөр бүр өөрийн горимыг МЭДНЭ (AC-21).
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    request_hash: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    filled_at: Mapped[datetime | None] = mapped_column(TS)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("side in ('buy','sell')", name="ck_orders_side"),
        CheckConstraint("qty > 0", name="ck_orders_qty_positive"),
        CheckConstraint(
            "origin in ('research_agent','auto_tuning','manual_operator','external')",
            name="ck_orders_origin",
        ),
        CheckConstraint("mode in ('paper','live')", name="ck_orders_mode"),
        Index("ix_orders_symbol_submitted", "symbol", "submitted_at"),
        Index("ix_orders_origin", "origin"),
        Index("ix_orders_status", "status"),
        UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
    )


class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(SAUuid, ForeignKey("orders.id"), nullable=False)
    broker_fill_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    qty: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    price: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    filled_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    #: Alpaca-ийн мэдээлсэн гүйцэтгэл. ЛОКАЛ ТООЦООЛОЛ БАЙХГҮЙ (LLD §5.3).
    raw: Mapped[dict] = mapped_column(JSON, nullable=False)


class AgentDecision(Base):
    __tablename__ = "agent_decisions"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    proposal: Mapped[dict] = mapped_column(JSON, nullable=False)
    grounding: Mapped[dict] = mapped_column(JSON, nullable=False)
    risk_evaluation: Mapped[dict | None] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (Index("ix_decisions_created", "created_at"),)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    response: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    called_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (Index("ix_tool_calls_session", "session_id"),)


class TuningHistory(Base):
    __tablename__ = "tuning_history"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    parameter: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[str] = mapped_column(Text, nullable=False)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    bounds: Mapped[dict] = mapped_column(JSON, nullable=False)
    backtest_window: Mapped[dict | None] = mapped_column(JSON)
    walk_forward: Mapped[dict] = mapped_column(JSON, nullable=False)
    applies_to: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        CheckConstraint("approved_by in ('system','operator')", name="ck_tuning_approved_by"),
        CheckConstraint("applies_to in ('backtest','paper','live')", name="ck_tuning_applies_to"),
    )


class AuditLog(Base):
    """Append-only, hash-chained (LLD §14).

    UPDATE/DELETE-ийг Postgres дээр RULE татгалзана (`migrations/`).
    """

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(SEQ, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(TS, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)


class SystemStateRow(Base):
    """Append-only төлөвийн түүх. Одоогийн төлөв = хамгийн их seq (LLD §5.8)."""

    __tablename__ = "system_state"

    seq: Mapped[int] = mapped_column(SEQ, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    wind_down_deadline: Mapped[datetime | None] = mapped_column(TS)

    __table_args__ = (
        CheckConstraint("state in ('active','winding_down','halted')", name="ck_system_state_value"),
        CheckConstraint(
            "changed_by in ('operator','circuit_breaker','scheduler')",
            name="ck_system_state_changed_by",
        ),
    )


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid)
    proposed_order: Mapped[dict] = mapped_column(JSON, nullable=False)
    risk_evaluation: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)
    resolved_by: Mapped[str | None] = mapped_column(Text)
    resolution_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "state in ('pending','approved','rejected','expired')", name="ck_approvals_state"
        ),
        Index("ix_approvals_pending", "state", "expires_at"),
    )


class Confirmation(Base):
    """Хоёр шаттай баталгаажуулалт — нэг удаа хэрэглэгдэнэ (LLD §8.4)."""

    __tablename__ = "confirmations"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(TS)


class BreakerEvent(Base):
    """Circuit breaker-ийн цонхны түүхий үйл явдал (LLD §15.2)."""

    __tablename__ = "breaker_events"

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ts: Mapped[datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (Index("ix_breaker_events_ts", "ts"),)
