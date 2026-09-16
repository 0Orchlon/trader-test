"""T-05 (ID=632) — лог redaction + secret pattern тест (NFR-3, AC-8)."""
from __future__ import annotations

import json

import pytest

from app.audit.redact import REDACTED, redact

KNOWN_SECRETS = [
    ("api_key", "PKTEST1234567890ABCD"),
    ("secret", "aBcD3fGh1jKlM0pQrStUvWxYz0123456789abcdE"),
    ("token", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.sig"),
    ("authorization", "Bearer sk-live-0123456789abcdef"),
    ("password", "hunter2-correct-horse"),
]


@pytest.mark.parametrize("key,value", KNOWN_SECRETS)
def test_secret_keys_are_redacted(key, value):
    out = redact({key: value, "nested": {key.upper(): value}})
    dumped = json.dumps(out)
    assert value not in dumped
    assert out[key] == REDACTED
    assert out["nested"][key.upper()] == REDACTED


def test_secret_value_patterns_redacted_even_under_innocent_key():
    out = redact({"note": "Bearer sk-live-0123456789abcdef дуудлаа"})
    assert "sk-live-0123456789abcdef" not in json.dumps(out)


def test_market_data_is_not_touched():
    """AC-8 — зөвхөн secret. Зах зээлийн түүхий payload өөрчлөгдөхгүй."""
    payload = {
        "bars": [{"o": "221.40", "h": "222.10", "c": "221.95", "v": 1_203_411}],
        "symbol": "AAPL",
        "quote_ts": "2026-09-16T14:30:00Z",
    }
    assert redact(payload) == payload


def test_key_ref_stays_but_key_material_never_appears():
    """LLD §14.3 — `key_ref` нь ЛАВЛАГАА тул үлдэнэ."""
    out = redact({"key_ref": "secretsmanager://p3/alpaca-paper", "api_key": "PKABC123XYZ456"})
    assert out["key_ref"] == "secretsmanager://p3/alpaca-paper"
    assert out["api_key"] == REDACTED


def test_lists_and_scalars_walked():
    out = redact({"calls": [{"headers": {"Authorization": "Bearer abc123def456ghi"}}]})
    assert out["calls"][0]["headers"]["Authorization"] == REDACTED
