"""`RiskContext`-ийн угсралт (LLD §8.3).

Дараалал ТОГТМОЛ бөгөөд бүх уншилт БОДИТ: `state_machine.current()` →
`get_account()` → `get_positions()` → `get_quote(symbol)` → `limits` → `now`.
Кэш БАЙХГҮЙ — Risk нь хуучин зурагнаас шийдвэр гаргах нь хамгийн чимээгүй
хэлбэрийн зөрчил.

`get_quote` унавал `quote=None` гэж ил тэмдэглэнэ: R4/R6/R7/R9 өөрсдөө
унаж REJECT гаргана. «Quote байхгүй тул алгасъя» гэсэн салаа БАЙХГҮЙ.

`session` өгөгдвөл (хувийн төсөл, LLD-д тусгаагүй): profit-cut ledger-ийн
нийлбэрийг Alpaca-ийн raw `equity`/`last_equity`-ээс хасаад л Risk-д өгнө.
`/account`-ийн raw пass-through-д ХЭЗЭЭ Ч хүрэхгүй (AC-1) — зөвхөн энэ
функцийн буцаах `RiskContext.account`-д нөлөөлнө.
"""
from __future__ import annotations

from dataclasses import replace

from app.broker.models import BrokerUnavailable, SystemState
from app.risk.agent import RiskContext
from app.risk.limits import RiskLimits
from app.util.time import now_utc


async def build(
    broker, settings, state: SystemState, symbol: str, *, idempotency_key: str = "", session=None
):
    account_envelope = await broker.get_account()
    positions_envelope = await broker.get_positions()
    try:
        quote = (await broker.get_quote(symbol)).data
    except BrokerUnavailable:
        quote = None
    account = account_envelope.data
    if session is not None:
        from app.capital.ledger import total_withdrawn

        withdrawn = await total_withdrawn(session)
        if withdrawn > 0:
            account = replace(
                account,
                equity=account.equity - withdrawn,
                last_equity=(
                    account.last_equity - withdrawn if account.last_equity is not None else None
                ),
            )
    return RiskContext(
        account=account,
        positions=list(positions_envelope.data),
        quote=quote,
        day_trade_count=account.day_trade_count,
        system_state=state,
        limits=RiskLimits.from_settings(settings),
        now=now_utc(),
        idempotency_key=idempotency_key,
    )
