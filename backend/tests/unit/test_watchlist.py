"""Алдагдалтай symbol-ыг код завсарлуулна — prompt биш (T-99)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app import models
from app.agents.watchlist import get_active_symbols
from app.util.time import now_utc


async def _close(session, symbol: str, pl: str, ago: timedelta = timedelta(hours=1)):
    session.add(
        models.Order(
            client_order_id=f"p3-close-{symbol}-{pl}-{ago.total_seconds()}",
            symbol=symbol,
            side="sell",
            qty=Decimal("1"),
            order_type="market",
            time_in_force="day",
            status="filled",
            origin="research_agent",
            risk_evaluation={"decision": "APPROVE"},
            mode="paper",
            submitted_at=now_utc() - ago,
            filled_at=now_utc() - ago,
            entry_price=Decimal("100"),
            realized_pl=Decimal(pl),
        )
    )
    await session.commit()


async def _watchlist(session, symbols: str):
    session.add(models.ResearchWatchlist(id=1, symbols=symbols, updated_at=now_utc()))
    await session.commit()


async def test_two_recent_losses_bench_the_symbol(db_session, settings):
    await _watchlist(db_session, "AAPL,MSFT")
    await _close(db_session, "AAPL", "-5", timedelta(hours=2))
    await _close(db_session, "AAPL", "-3", timedelta(hours=1))

    assert await get_active_symbols(db_session, settings) == ["MSFT"]


async def test_crypto_symbol_matches_stored_form(db_session, settings):
    await _watchlist(db_session, "BTC/USD,MSFT")
    await _close(db_session, "BTCUSD", "-5", timedelta(hours=2))
    await _close(db_session, "BTCUSD", "-3", timedelta(hours=1))

    assert await get_active_symbols(db_session, settings) == ["MSFT"]


async def test_old_or_net_positive_closes_do_not_bench(db_session, settings):
    await _watchlist(db_session, "AAPL,MSFT")
    # Сүүлийн хаалт 24 цагаас хуучин.
    await _close(db_session, "AAPL", "-5", timedelta(hours=30))
    await _close(db_session, "AAPL", "-3", timedelta(hours=26))
    # Цэвэр дүнгээр ашигтай.
    await _close(db_session, "MSFT", "-3", timedelta(hours=2))
    await _close(db_session, "MSFT", "10", timedelta(hours=1))

    assert await get_active_symbols(db_session, settings) == ["AAPL", "MSFT"]


async def test_benching_everything_degrades_to_full_list(db_session, settings):
    await _watchlist(db_session, "AAPL,MSFT")
    for symbol in ("AAPL", "MSFT"):
        await _close(db_session, symbol, "-5", timedelta(hours=2))
        await _close(db_session, symbol, "-3", timedelta(hours=1))

    assert await get_active_symbols(db_session, settings) == settings.research_symbols
