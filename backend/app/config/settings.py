"""Settings (LLD §17.1).

§7-ийн хязгаарууд болон цагийн параметрүүд нь **анхдагч утгагүй**. Дутуу бол
`ValidationError` → app эхлэхгүй (P-2). «Унтаа анхдагч руу унах» зам БАЙХГҮЙ.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from functools import lru_cache
from typing import ClassVar

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.mode import TradingMode, broker_host, resolve_mode


#: Анхдагч утгатай БАЙЖ БОЛОХГҮЙ талбарууд — тест үүнийг шалгана (AC-13).
REQUIRED_LIMIT_FIELDS: tuple[str, ...] = (
    "MAX_ORDER_NOTIONAL",
    "MAX_POSITION_PCT",
    "MAX_TOTAL_EXPOSURE_PCT",
    "DAILY_LOSS_LIMIT",
    "MAX_DAY_TRADES",
    "PRICE_SANITY_PCT",
    "APPROVAL_TTL",
    "WIND_DOWN_GRACE",
    "CONFIRMATION_TTL",
    "STALE_AFTER_SECONDS",
)


class Settings(BaseSettings):
    REQUIRED_LIMIT_FIELDS: ClassVar[tuple[str, ...]] = REQUIRED_LIMIT_FIELDS
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- горим ---
    ALPACA_ENV: str = "paper"
    LIVE_TRADING_ACKNOWLEDGED: bool = False
    LIVE_CHECKLIST_SIGNATURE: str | None = None
    ALPACA_KEY_REF: str
    ALPACA_API_KEY: str | None = None
    ALPACA_API_SECRET: str | None = None

    # --- §7-ийн хязгаарууд (анхдагчгүй) ---
    MAX_ORDER_NOTIONAL: Decimal
    MAX_POSITION_PCT: Decimal
    MAX_TOTAL_EXPOSURE_PCT: Decimal
    DAILY_LOSS_LIMIT: Decimal
    MAX_DAY_TRADES: int
    PRICE_SANITY_PCT: Decimal
    APPROVAL_TTL: timedelta
    WIND_DOWN_GRACE: timedelta
    CONFIRMATION_TTL: timedelta
    STALE_AFTER_SECONDS: int

    # --- бусад анхдагчгүй тохиргоо (§17.1) ---
    GROUNDING_TOLERANCE: Decimal
    BREAKER_WINDOW: int
    PROVIDER_ERROR_THRESHOLD: int
    RECONCILE_DRIFT_LIMIT: int
    ERROR_RATE_LIMIT: Decimal
    REJECT_RATE_LIMIT: Decimal
    WS_DISCONNECT_LIMIT: int

    RESTRICTED_SYMBOLS: str = ""

    # --- автономи research loop (LLD-д тусгаагүй, T-99 хувийн төсөл) ---
    #: Гурвын аль нь ч байхгүй бол `run_research_cycle` чимээгүй алгасна —
    #: провайдер тохируулаагүй нь эвдрэл БИШ.
    ANTHROPIC_API_KEY: str | None = None
    CLAUDE_MODEL: str = "claude-opus-5"
    LOCAL_MODEL_URL: str | None = None
    LOCAL_MODEL_NAME: str = "llama3.1"
    RESEARCH_SYMBOLS: str = "AAPL,MSFT,SPY"
    RESEARCH_INTERVAL_SECONDS: int = 300
    RESEARCH_MAX_TOOL_TURNS: int = 6

    # --- дэд бүтэц ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./p3.db"
    REDIS_URL: str | None = None
    HEARTBEAT_SECONDS: int = 2

    @field_validator("APPROVAL_TTL", "WIND_DOWN_GRACE", "CONFIRMATION_TTL", mode="before")
    @classmethod
    def _seconds(cls, v):
        """`.env`-д секундын бүхэл тоо бичигдэнэ — ISO-8601 биш."""
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().lstrip("-").isdigit()):
            return timedelta(seconds=int(v))
        return v

    @field_validator("DAILY_LOSS_LIMIT")
    @classmethod
    def _negative_loss_limit(cls, v: Decimal) -> Decimal:
        """Хязгаар нь СӨРӨГ — энэ нь өдрийн P&L-ийн доод шал (N-3).

        `r8` нь `pnl > limit` бол зөвшөөрнө, breaker нь `pnl <= limit` бол
        зогсооно. Эерэг утга нь хоёуланг нь шууд идэвхжүүлж, систем
        чимээгүй бүтэн түгжигдэнэ — тиймээс энэ нь эхлэхээс өмнө УНАНА.
        """
        if v >= 0:
            raise ValueError("DAILY_LOSS_LIMIT нь сөрөг байх ёстой (ж: -2000.00)")
        return v

    @field_validator("RESTRICTED_SYMBOLS")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def restricted_symbols(self) -> frozenset[str]:
        return frozenset(s.strip() for s in self.RESTRICTED_SYMBOLS.split(",") if s.strip())

    @property
    def research_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.RESEARCH_SYMBOLS.split(",") if s.strip()]

    @property
    def mode(self) -> TradingMode:
        return resolve_mode(self)

    @property
    def broker_host(self) -> str:
        return broker_host(self.mode)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
