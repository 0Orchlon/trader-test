"""Хариу угсрах давхарга — AC-20, AC-21, AC-25, AC-26 (T-07).

Гурван үл хөдлөх дүрэм НЭГ газар биелдэг:

1. Мөнгө нь fixed-point **тэмдэгт мөр**. `float` дамжуулах оролдлого
   `TypeError` — тоймлолт чимээгүй алдагдахаас өмнө зогсоно.
2. Timestamp бүр UTC `Z`.
3. Хариу бүр `source`-той; нэг хариунд ХОЛИМОГ `source` байхыг
   `single_source()` барина.

Дүрмийг энд төвлөрүүлсэн шалтгаан: route бүр өөрөө угсарвал нэг route
мартахад л гэрээ чимээгүй зөрчигдөнө.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from app.broker.models import Source, SystemState
from app.util.money import money_str, qty_str
from app.util.time import now_utc, to_iso


class MixedSourceError(RuntimeError):
    """Нэг хариунд хоёр өөр `source` нийлүүлэх оролдлого (AC-20).

    Backtest-ийн мөрийг live жагсаалтад нийлүүлэх нь operator-ыг хамгийн
    үнэтэй байдлаар төөрөгдүүлнэ — тиймээс энэ нь алдаа, анхааруулга биш.
    """


def single_source(sources: Iterable[Source]) -> Source:
    unique = {Source(s) for s in sources}
    if len(unique) > 1:
        raise MixedSourceError(f"нэг хариунд холимог source: {sorted(s.value for s in unique)}")
    if not unique:
        raise MixedSourceError("source байхгүй — хоосон хариунд ч гарал заавал")
    return unique.pop()


def money_field(value: Decimal | None) -> str | None:
    if isinstance(value, float):
        raise TypeError("мөнгөн талбарт float хоригтой (AC-25) — Decimal ашигла")
    return money_str(value)


def qty_field(value: Decimal | None) -> str | None:
    if isinstance(value, float):
        raise TypeError("тоо ширхэгт float хоригтой (AC-25) — Decimal ашигла")
    return qty_str(value)


def _assert_no_floats(payload: Any, path: str = "$") -> None:
    if isinstance(payload, float):
        raise TypeError(f"{path}: float хариунд хоригтой (AC-25)")
    if isinstance(payload, dict):
        for key, value in payload.items():
            _assert_no_floats(value, f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        for i, value in enumerate(payload):
            _assert_no_floats(value, f"{path}[{i}]")


def envelope(
    body: dict[str, Any],
    *,
    source: Source,
    system_state: SystemState,
    as_of=None,
    stale: bool = False,
) -> dict[str, Any]:
    """`Envelope` + бие. `source` нь заавал — анхдагч БАЙХГҮЙ."""
    resolved = Source(source)  # enum-аас гадуур утга энд унана
    _assert_no_floats(body)
    return {
        "source": resolved.value,
        "as_of": to_iso(as_of or now_utc()),
        # Талбарыг ОРХИХГҮЙ: «байхгүй» нь клиентэд таамаглах цонх өгнө.
        "stale": bool(stale),
        "system_state": SystemState(system_state).value,
        **body,
    }
