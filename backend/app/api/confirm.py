"""Хоёр шаттай баталгаажуулалт (LLD §8.4, AC-38).

Token нь **үйлдэл + биеийн hash**-д уягдана: өөр үйлдлийн token дамжуулах,
эсвэл баталсан биеийг сольж илгээх боломжгүй. Нэг удаа хэрэглэгдэнэ.

Сорилтын текст (`prompt`) нь үйлдэл тус бүрд ӨӨР — «Зогсоо» ба «Идэвхжүүл»
хоёрыг андуурах нь энэ системд хамгийн үнэтэй алдаа (AC-38).
"""
from __future__ import annotations

import json
import secrets
from hashlib import sha256
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.api.problem import problem
from app.util.time import now_utc, to_iso

PROMPTS = {
    "system_activate": "Системийг ИДЭВХЖҮҮЛЭХ үү? Agent болон алгоритм арилжаагаа дахин эхлүүлнэ.",
    "manual_order": "Энэ хэмжээний ГАРЫН ORDER-ыг илгээх үү? Хязгаараас дээш байна.",
    "tuning_promote": "Тохируулсан параметрийг LIVE руу ДЭВШҮҮЛЭХ үү?",
}


def payload_hash(payload: Any) -> bytes:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).digest()


async def issue(session: AsyncSession, action: str, payload: Any, *, ttl) -> dict:
    token = secrets.token_hex(32)
    expires_at = now_utc() + ttl
    session.add(
        models.Confirmation(
            token=token,
            action=action,
            payload_hash=payload_hash(payload),
            created_at=now_utc(),
            expires_at=expires_at,
        )
    )
    await session.commit()
    return {"token": token, "prompt": PROMPTS[action], "expires_at": to_iso(expires_at)}


async def consume(session: AsyncSession, token: str, action: str, payload: Any) -> None:
    """Алдаа бүр `confirmation_required` — «яагаад» гэдэг нь ил, хариу нэг.

    Хугацаа дууссан, хэрэглэгдсэн, өөр үйлдлийн, өөр биетэй — бүгд ижил
    үр дүн: operator дахин баталгаажуулна.
    """
    row = await session.get(models.Confirmation, token)
    if row is None:
        raise problem("confirmation_required", 409, "баталгаажуулалтын token олдсонгүй")
    if row.consumed_at is not None:
        raise problem("confirmation_required", 409, "token аль хэдийн хэрэглэгдсэн")
    if row.expires_at <= now_utc():
        raise problem("confirmation_required", 409, "token-ийн хугацаа дууссан")
    if row.action != action:
        raise problem("confirmation_required", 409, "token өөр үйлдлийнх")
    if row.payload_hash != payload_hash(payload):
        raise problem("confirmation_required", 409, "баталсан бие өөрчлөгдсөн")
    row.consumed_at = now_utc()
    await session.commit()
