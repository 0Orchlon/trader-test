"""Audit log — hash chain (LLD §14.1, AC-17).

Hash-ийн ЯГ тодорхойлолт. Канон серилизаци (`sort_keys` + нягт `separators`)
нь өөр дарааллаар бичигдсэн ижил payload-аас ижил hash гаргана — эсрэг
тохиолдолд verifier худал сэрэмжлүүлэг өгнө.
"""
from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.audit.redact import redact
from app.util.time import ensure_utc, now_utc

GENESIS_HASH = b"\x00" * 32


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def compute_hash(
    prev_hash: bytes,
    seq: int,
    ts: datetime,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
) -> bytes:
    return sha256(
        prev_hash
        + seq.to_bytes(8, "big")
        + ensure_utc(ts).isoformat().encode()
        + event_type.encode()
        + actor.encode()
        + canonical_payload(payload)
    ).digest()


class AuditChain:
    """Нэг session дотор дараалсан бичилт. Транзакцийг дуудагч эзэмшинэ —
    төлөвийн шилжилт ба audit мөр НЭГ транзакцид орох ёстой (LLD §6.2).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _tip(self) -> tuple[int, bytes]:
        row = (
            await self.session.execute(
                select(models.AuditLog.seq, models.AuditLog.hash)
                .order_by(models.AuditLog.seq.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return 0, GENESIS_HASH
        return int(row.seq), row.hash

    async def append(
        self, event_type: str, actor: str, payload: dict[str, Any]
    ) -> models.AuditLog:
        last_seq, prev_hash = await self._tip()
        seq = last_seq + 1
        ts = now_utc()
        safe_payload = redact(payload)
        row = models.AuditLog(
            seq=seq,
            ts=ts,
            event_type=event_type,
            actor=actor,
            payload=safe_payload,
            prev_hash=prev_hash,
            hash=compute_hash(prev_hash, seq, ts, event_type, actor, safe_payload),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def count(self) -> int:
        return int((await self.session.execute(select(func.count(models.AuditLog.seq)))).scalar_one())
