"""Redaction (LLD §14.3, T-05, NFR-3).

Allow-list БИШ — **түлхүүрийн нэр + утгын хэв маяг** хосолсон. Зөвхөн secret
арилна; зах зээлийн түүхий payload өөрчлөгдөхгүй (AC-8).
"""
from __future__ import annotations

import re
from typing import Any

REDACTED = "«REDACTED»"

#: Түлхүүрийн нэрээр (том/жижиг үсэг хамаарахгүй, дэд мөрөөр таарна).
SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "authorization",
    "password",
    "passwd",
    "credential",
    "private_key",
)

#: `key_ref` нь ЛАВЛАГАА — утга нь түлхүүр БИШ тул үлдэнэ (LLD §14.3).
KEY_WHITELIST = ("key_ref", "tool_call_id", "decision_id", "confirmation_token_id")

#: Утгын хэв маягаар — «гэмгүй» түлхүүрийн дор нуугдсан secret-ийг барина.
SECRET_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9\-]{12,}\b"),
    re.compile(r"\bPK[A-Z0-9]{10,}\b"),  # Alpaca key
    re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{2,}\b"),  # JWT
)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in KEY_WHITELIST:
        return False
    return any(part in lowered for part in SECRET_KEY_PARTS)


def _scrub_value(value: str) -> str:
    out = value
    for pattern in SECRET_VALUE_PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def redact(value: Any) -> Any:
    """Рекурсив. Хэлбэрийг хадгална — зөвхөн утгыг сольж болно."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if _is_secret_key(str(k)) else redact(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _scrub_value(value)
    return value
