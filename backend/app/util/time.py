"""Instant-ийн хилийн дүрэм (LLD §4, AC-26).

`datetime.now()` кодод хоригтой — зөвхөн `now_utc()`. Naive datetime нь алдаа.
"""
from __future__ import annotations

from datetime import UTC, datetime


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"naive datetime хоригтой: {value!r}")
    return value.astimezone(UTC)


def to_iso(value: datetime | None) -> str | None:
    """RFC 3339, ЗААВАЛ `Z` төгсгөлтэй (contracts.yaml `Utc`)."""
    if value is None:
        return None
    return ensure_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(text: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
