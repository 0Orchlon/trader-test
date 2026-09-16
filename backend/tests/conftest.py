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
async def engine(tmp_path):
    from app import models  # noqa: F401
    from app.db import Base, enable_sqlite_foreign_keys, make_engine

    url = f"sqlite+aiosqlite:///{tmp_path.as_posix()}/test.db"
    engine = make_engine(url)
    await enable_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine):
    from app.db import make_sessionmaker

    async with make_sessionmaker(engine)() as session:
        yield session


@pytest.fixture
def settings(limit_env):
    from app.config.settings import Settings

    return Settings(**limit_env)


@pytest.fixture
def bus():
    from app.stream.bus import EventBus

    return EventBus()


@pytest.fixture
def broker():
    from tests.fakes import FakeBroker

    return FakeBroker()


@pytest.fixture
async def app(engine, settings, bus, broker):
    """Бодит FastAPI app — route-ууд нь prod-ийнхтэй ЯГ ижил.

    Ялгаа нь зөвхөн broker (хуурамч) ба DB (SQLite). Route-ыг тестэд зориулж
    дахин утаслах нь тестийг бодит замаас салгана.
    """
    from app.main import create_app

    application = create_app(engine=engine, settings=settings, broker=broker, bus=bus)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def seeded_orders(db_session):
    """Хоёр origin-той хоёр order — attribution / шүүлтийн тестийн суурь."""
    from decimal import Decimal

    from app import models
    from app.util.time import now_utc

    rows = [
        models.Order(
            client_order_id="p3-seed-agent",
            broker_order_id="brk-agent",
            symbol="AAPL",
            side="buy",
            qty=Decimal("10"),
            filled_qty=Decimal("10"),
            order_type="limit",
            limit_price=Decimal("221.50"),
            time_in_force="day",
            status="filled",
            origin="research_agent",
            origin_detail="claude-mcp/claude-opus-5",
            risk_evaluation={"decision": "APPROVE"},
            mode="paper",
            submitted_at=now_utc(),
        ),
        models.Order(
            client_order_id="p3-seed-manual",
            broker_order_id="brk-manual",
            symbol="MSFT",
            side="sell",
            qty=Decimal("12"),
            filled_qty=Decimal("0"),
            order_type="market",
            time_in_force="day",
            status="accepted",
            origin="manual_operator",
            origin_detail="operator",
            risk_evaluation={"decision": "APPROVE"},
            mode="paper",
            submitted_at=now_utc(),
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return rows
