"""`resolve_mode()` — live болох гурван ил дохио (LLD §17.2, P-3, AC-12)."""
from __future__ import annotations

from enum import StrEnum


class ConfigError(RuntimeError):
    """Тохиргоо дутуу. Чимээгүй `paper` руу УНАХГҮЙ — зогсоно."""


class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


PAPER_HOST = "paper-api.alpaca.markets"
LIVE_HOST = "api.alpaca.markets"


def resolve_mode(env) -> TradingMode:
    if getattr(env, "ALPACA_ENV", "paper") != "live":
        return TradingMode.PAPER
    if not getattr(env, "LIVE_TRADING_ACKNOWLEDGED", False):
        raise ConfigError(
            "ALPACA_ENV=live боловч LIVE_TRADING_ACKNOWLEDGED тавигдаагүй — "
            "paper руу унахгүй, зогсож байна"
        )
    if getattr(env, "LIVE_CHECKLIST_SIGNATURE", None) is None:
        raise ConfigError(
            "ALPACA_ENV=live боловч LIVE_CHECKLIST_SIGNATURE байхгүй — "
            "гарын үсэг зурсан checklist шаардлагатай (FR-2)"
        )
    return TradingMode.LIVE


def broker_host(mode: TradingMode) -> str:
    return LIVE_HOST if mode is TradingMode.LIVE else PAPER_HOST
