"""Approval TTL reaper (T-17, LLD §15.3, AC-6).

30 секунд тутам ажиллана. Энэ нь **цэвэрлэгээ**, ХААЛГА биш: `approve` нь
`expires_at`-ыг өөрөө шалгадаг тул reaper хожимдсон ч хугацаа дууссан мөр
гүйцэтгэгдэхгүй. Хоёр газарт шалгах нь давхардал биш — reaper унасан ч
хаалга хэвээр.

`version` ахина: reaper-тэй уралдсан `approve` нь `expected_version`-оор
409 авна.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.approvals.queue import EXPIRED, PENDING
from app.audit.chain import AuditChain
from app.util.time import now_utc


async def expire_due(session: AsyncSession) -> int:
    """Хугацаа дууссан `pending` мөрүүдийг `expired` болгоно. Тоог буцаана."""
    now = now_utc()
    rows = list(
        (
            await session.execute(
                select(models.Approval)
                .where(models.Approval.state == PENDING)
                .where(models.Approval.expires_at <= now)
            )
        ).scalars()
    )
    chain = AuditChain(session)
    for row in rows:
        row.state = EXPIRED
        row.version += 1
        row.resolved_at = now
        row.resolved_by = "scheduler"
        row.resolution_reason = "expired"
        await chain.append(
            "approval_expired",
            "system:scheduler",
            {"approval_id": str(row.id), "symbol": row.proposed_order.get("symbol")},
        )
    if rows:
        await session.commit()
    return len(rows)
