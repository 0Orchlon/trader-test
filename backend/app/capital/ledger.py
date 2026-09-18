"""Profit-cut ledger (хувийн төсөл, LLD-д тусгаагүй).

Alpaca руу ЮУ Ч илгээхгүй — эрхийн хасалт бол ЗӨВХӨН локал бүртгэл.
Нийлбэр (`total_withdrawn`) нь `app.api.risk_context.build`-ийн үр дүнтэй
equity-г тооцоход л хэрэглэгдэнэ; `/account`-ийн raw Alpaca утгыг ХЭЗЭЭ Ч
өөрчлөхгүй (AC-1).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.audit.chain import AuditChain
from app.util.time import now_utc


class InvalidWithdrawal(ValueError):
    """`amount`/`pct` хоёулаа өгөгдсөн, эсвэл аль нь ч байхгүй, эсвэл ≤0."""


async def total_withdrawn(session: AsyncSession) -> Decimal:
    total = (
        await session.execute(select(func.coalesce(func.sum(models.CapitalWithdrawal.amount), 0)))
    ).scalar_one()
    return Decimal(str(total))


async def withdraw(
    session: AsyncSession,
    broker,
    *,
    amount: Decimal | None = None,
    pct: Decimal | None = None,
    note: str | None = None,
) -> models.CapitalWithdrawal:
    if (amount is None) == (pct is None):
        raise InvalidWithdrawal("`amount` эсвэл `pct`-ийн ЗӨВХӨН нэгийг өг")

    equity = (await broker.get_account()).data.equity
    if pct is not None:
        if pct <= 0 or pct > 100:
            raise InvalidWithdrawal(f"pct нь (0, 100] мужид байх ёстой: {pct}")
        amount = (equity * pct / Decimal("100")).quantize(Decimal("0.01"))
    elif amount <= 0:
        raise InvalidWithdrawal(f"amount эерэг байх ёстой: {amount}")

    row = models.CapitalWithdrawal(
        amount=amount,
        pct=pct,
        equity_at_withdrawal=equity,
        note=note,
        created_at=now_utc(),
    )
    session.add(row)
    await session.flush()
    await AuditChain(session).append(
        "capital_withdrawn",
        "operator",
        {
            "withdrawal_id": str(row.id),
            "amount": str(amount),
            "pct": str(pct) if pct is not None else None,
            "equity_at_withdrawal": str(equity),
            "note": note,
        },
    )
    await session.commit()
    return row
