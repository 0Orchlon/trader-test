"""T-06 (ID=633) — BrokerPort + AlpacaAdapter (унших зам).

LLD §7: Alpaca-ийн хариу нь домэйн модель рүү ЗӨВХӨН БУУЛГАГДАНА, дахин
тооцогдохгүй (AC-1).
"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from app.broker.alpaca import AlpacaAdapter
from app.broker.models import BrokerUnavailable, PositionSide, Source
from app.config.mode import TradingMode

ACCOUNT_JSON = {
    "id": "PA3X9QK2TLZ0",
    "equity": "104238.17",
    "cash": "38210.55",
    "buying_power": "76421.10",
    "last_equity": "103980.44",
    "pattern_day_trader": False,
    "daytrade_count": 1,
    "trading_blocked": False,
}

POSITION_JSON = [
    {
        "symbol": "AAPL",
        "qty": "40",
        "side": "long",
        "avg_entry_price": "221.40",
        # Санаатай «зөрүүтэй» — qty × avg = 8856.00 боловч Alpaca 9012.00 гэж хэлж
        # байна. Систем Alpaca-ийн хэлснийг л авна.
        "market_value": "9012.00",
        "unrealized_pl": "156.00",
    }
]

SNAPSHOT_JSON = {
    "symbol": "AAPL",
    "latestQuote": {"bp": "221.30", "ap": "221.50", "t": "2026-09-16T14:30:00Z"},
    "latestTrade": {"p": "221.44", "t": "2026-09-16T14:29:59Z"},
}


def _adapter(handler, mode=TradingMode.PAPER) -> AlpacaAdapter:
    transport = httpx.MockTransport(handler)
    return AlpacaAdapter(
        mode=mode,
        api_key="k",
        api_secret="s",
        client=httpx.AsyncClient(transport=transport, base_url="https://paper-api.alpaca.markets"),
    )


async def test_account_is_mapped_not_recomputed():
    adapter = _adapter(lambda r: httpx.Response(200, json=ACCOUNT_JSON))
    env = await adapter.get_account()
    assert env.source is Source.ALPACA_PAPER
    assert env.data.equity == Decimal("104238.17")
    assert env.data.day_trade_count == 1
    assert env.stale is False


async def test_position_market_value_comes_from_alpaca_never_qty_times_price():
    """AC-1 — локал `qty × price` тооцоо ХЭЗЭЭ Ч хийгдэхгүй."""
    adapter = _adapter(lambda r: httpx.Response(200, json=POSITION_JSON))
    env = await adapter.get_positions()
    pos = env.data[0]
    assert pos.market_value == Decimal("9012.00")
    assert pos.market_value != pos.qty * pos.avg_entry_price
    assert pos.side is PositionSide.LONG


async def test_quote_last_comes_from_latest_trade_not_from_mid():
    adapter = _adapter(lambda r: httpx.Response(200, json=SNAPSHOT_JSON))
    env = await adapter.get_quote("AAPL")
    assert env.data.bid == Decimal("221.30")
    assert env.data.ask == Decimal("221.50")
    # mid нь 221.40 байх байсан — ТООЦООЛОХГҮЙ, Alpaca-ийн сүүлийн арилжаа.
    assert env.data.last == Decimal("221.44")


async def test_missing_trade_is_an_error_not_a_guessed_price():
    payload = {"symbol": "AAPL", "latestQuote": SNAPSHOT_JSON["latestQuote"]}
    adapter = _adapter(lambda r: httpx.Response(200, json=payload))
    with pytest.raises(BrokerUnavailable):
        await adapter.get_quote("AAPL")


async def test_unreachable_raises_and_never_returns_cached():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectError("no route")

    adapter = _adapter(handler)
    with pytest.raises(BrokerUnavailable):
        await adapter.get_account()
    # Retry нь зөвхөн УНШИХ дуудалтад, 3 оролдлого (LLD §7).
    assert calls["n"] == 3


async def test_live_host_is_blocked_inside_tests(_live_egress_guard):
    """AC-12 — тестийн явцад live Alpaca руу 0 дуудалт, хэмжигдсэн баримт."""
    from app.config.egress import LiveEgressViolation

    adapter = AlpacaAdapter(mode=TradingMode.LIVE, api_key="k", api_secret="s")
    assert adapter.source is Source.ALPACA_LIVE
    with pytest.raises(LiveEgressViolation):
        await adapter.get_account()
    assert _live_egress_guard.blocked  # барьсан
    _live_egress_guard.blocked.clear()  # энэ тест зориудаар оролдсон


# --- N-3: broker-ийн ТАТГАЛЗАЛ ≠ broker-ийн УНАЛТ ---

WASH_TRADE = {"code": 42210000, "message": "potential wash trade detected. use complex orders"}


def _order() -> "ValidatedOrder":
    from app.broker.models import OrderSide, OrderType, TimeInForce, ValidatedOrder

    return ValidatedOrder(
        symbol="AAPL",
        side=OrderSide.BUY,
        qty=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        limit_price=None,
        stop_price=None,
        client_order_id="p3-wash-1",
    )


async def test_wash_trade_403_is_a_rejection_not_an_outage():
    """Alpaca хариулсан = Alpaca АМЬД. 503 гэж хэлэх нь худал оношилгоо."""
    from app.broker.models import BrokerRejected

    adapter = _adapter(lambda r: httpx.Response(403, json=WASH_TRADE))
    with pytest.raises(BrokerRejected) as caught:
        await adapter.submit_order(_order())
    assert caught.value.broker_code == "42210000"
    assert "wash trade" in caught.value.message
    assert not isinstance(caught.value, BrokerUnavailable)


async def test_a_rejection_does_not_inflate_the_api_error_rate():
    """`api_error_rate` нь ХҮРЭХГҮЙ БАЙДЛЫН метрик — татгалзал түүнийг бохирдуулахгүй."""
    reported: list[bool] = []
    adapter = _adapter(lambda r: httpx.Response(403, json=WASH_TRADE))

    async def reporter(ok: bool) -> None:
        reported.append(ok)

    adapter.bind_api_reporter(reporter)
    from app.broker.models import BrokerRejected

    with pytest.raises(BrokerRejected):
        await adapter.submit_order(_order())
    assert reported == [True]


async def test_server_error_is_still_an_outage():
    reported: list[bool] = []
    adapter = _adapter(lambda r: httpx.Response(500, text="boom"))

    async def reporter(ok: bool) -> None:
        reported.append(ok)

    adapter.bind_api_reporter(reporter)
    with pytest.raises(BrokerUnavailable):
        await adapter.submit_order(_order())
    assert reported == [False]


async def test_unauthorized_401_is_an_outage_not_an_order_rejection():
    """Түлхүүр буруу бол ямар ч order илгээгдэхгүй — энэ нь татгалзал БИШ."""
    adapter = _adapter(lambda r: httpx.Response(401, json={"code": 40110000, "message": "auth"}))
    with pytest.raises(BrokerUnavailable):
        await adapter.submit_order(_order())


async def test_rate_limit_429_is_an_outage_not_an_order_rejection():
    adapter = _adapter(lambda r: httpx.Response(429, json={"message": "too many requests"}))
    with pytest.raises(BrokerUnavailable):
        await adapter.submit_order(_order())
