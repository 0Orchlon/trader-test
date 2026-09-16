"""`RiskLimits` — §7-ийн тоон хязгаарууд, хөлдөөсөн (LLD §8).

Утгууд нь config-оос ирнэ. ЭНД анхдагч утга БАЙХГҮЙ — «унтаа анхдагч руу унах»
зам нь хязгаарыг чимээгүй сулруулна (P-2, AC-13).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_order_notional: Decimal
    max_position_pct: Decimal
    max_total_exposure_pct: Decimal
    daily_loss_limit: Decimal
    max_day_trades: int
    price_sanity_pct: Decimal
    restricted_symbols: frozenset[str]

    @classmethod
    def from_settings(cls, settings) -> "RiskLimits":
        return cls(
            max_order_notional=settings.MAX_ORDER_NOTIONAL,
            max_position_pct=settings.MAX_POSITION_PCT,
            max_total_exposure_pct=settings.MAX_TOTAL_EXPOSURE_PCT,
            daily_loss_limit=settings.DAILY_LOSS_LIMIT,
            max_day_trades=settings.MAX_DAY_TRADES,
            price_sanity_pct=settings.PRICE_SANITY_PCT,
            restricted_symbols=settings.restricted_symbols,
        )


#: PDT дүрэм нь зөвхөн $25k-аас доош equity-д хамаарна (SEC).
PDT_EQUITY_FLOOR = Decimal("25000.00")
