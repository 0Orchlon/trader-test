"""Тестийн нийтлэг суурь.

`LiveEgressGuard` энд opt-out БАЙХГҮЙГЭЭР идэвхжинэ (LLD §17.3, AC-12):
тестийн явцад `api.alpaca.markets` руу гарах ямар ч дуудалт AssertionError.
"""
from __future__ import annotations

import pytest

LIMIT_ENV = {
    "ALPACA_ENV": "paper",
    "ALPACA_KEY_REF": "secretsmanager://p3/alpaca-paper",
    "MAX_ORDER_NOTIONAL": "5000.00",
    "MAX_POSITION_PCT": "10",
    "MAX_TOTAL_EXPOSURE_PCT": "60",
    "DAILY_LOSS_LIMIT": "-2000.00",
    "MAX_DAY_TRADES": "3",
    "PRICE_SANITY_PCT": "10",
    "APPROVAL_TTL": "900",
    "WIND_DOWN_GRACE": "900",
    "CONFIRMATION_TTL": "300",
    "STALE_AFTER_SECONDS": "5",
    "GROUNDING_TOLERANCE": "0",
    "BREAKER_WINDOW": "300",
    "PROVIDER_ERROR_THRESHOLD": "3",
    "RECONCILE_DRIFT_LIMIT": "2",
    "ERROR_RATE_LIMIT": "0.05",
    "REJECT_RATE_LIMIT": "0.5",
    "WS_DISCONNECT_LIMIT": "5",
    "RESTRICTED_SYMBOLS": "GME,AMC",
}


@pytest.fixture
def limit_env() -> dict[str, str]:
    return dict(LIMIT_ENV)


@pytest.fixture(autouse=True)
def _live_egress_guard(monkeypatch):
    from app.config import egress

    guard = egress.LiveEgressGuard()
    monkeypatch.setattr(egress, "ACTIVE_GUARD", guard)
    yield guard
    assert guard.blocked == [], f"тестийн явцад live host руу дуудалт: {guard.blocked}"


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch):
    for k, v in LIMIT_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
async def db_session(tmp_path, monkeypatch):
    from app import models  # noqa: F401
    from app.db import Base, enable_sqlite_foreign_keys, make_engine, make_sessionmaker

    url = f"sqlite+aiosqlite:///{tmp_path.as_posix()}/test.db"
    engine = make_engine(url)
    await enable_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = make_sessionmaker(engine)
    async with maker() as session:
        yield session
    await engine.dispose()
