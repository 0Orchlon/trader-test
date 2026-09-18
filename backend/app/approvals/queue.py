"""Approval queue (T-17, LLD §9.4, AC-5, AC-6).

`ESCALATE_TO_HUMAN` → энд мөр үүснэ. Мөр үүсэх нь Alpaca руу дуудалт БИШ:
approve дарагдтал broker огт хөндөгдөхгүй.

`version` нь optimistic lock. Reaper (TTL) ч, operator ч мөрийг ӨӨРЧЛӨХДӨӨ
version-ыг ахиулна — уралдаан 409-ээр төгсөнө, чимээгүй давхар зөвшөөрлөөр биш.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.broker.models import OrderIntent, OrderSide, OrderType, TimeInForce
from app.util.time import now_utc

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EXPIRED = "expired"

RESOLVED_STATES = (APPROVED, REJECTED, EXPIRED)


async def create_approval(
    session: AsyncSession,
    *,
    decision_id: uuid.UUID | None,
    proposed_order: dict,
    risk_evaluation: dict,
    ttl: timedelta,
) -> models.Approval:
    created = now_utc()
    row = models.Approval(
        version=1,
        state=PENDING,
        decision_id=decision_id,
        proposed_order=proposed_order,
        risk_evaluation=risk_evaluation,
        created_at=created,
        expires_at=created + ttl,
    )
    session.add(row)
    await session.flush()
    return row


async def pending(session: AsyncSession) -> list[models.Approval]:
    return list(
        (
            await session.execute(
                select(models.Approval)
                .where(models.Approval.state == PENDING)
                .order_by(models.Approval.created_at)
            )
        ).scalars()
    )


def intent_from(proposed_order: dict) -> OrderIntent:
    """`ProposedOrder` → Risk-ийн оролт.

    `rationale` / `grounded_in` нь ЭНД ирэхгүй: Risk нь үндэслэлийг шүүхгүй,
    тоог шүүнэ. Үндэслэлийн шалгалт нь grounding checker-ийн ажил (§13).
    """
    return OrderIntent(
        symbol=str(proposed_order["symbol"]).upper(),
        side=OrderSide(proposed_order["side"]),
        qty=Decimal(str(proposed_order["qty"])),
        order_type=OrderType(proposed_order["order_type"]),
        time_in_force=TimeInForce(proposed_order.get("time_in_force", "day")),
        limit_price=_optional(proposed_order.get("limit_price")),
        stop_price=_optional(proposed_order.get("stop_price")),
    )


def origin_detail_of(proposed_order: dict) -> str:
    return f"{proposed_order.get('provider', 'unknown')}/{proposed_order.get('model', 'unknown')}"


def _optional(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))
