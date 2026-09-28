"""T-06 (ID=633) — BrokerPort + AlpacaAdapter (унших зам).

LLD §7: Alpaca-ийн хариу нь домэйн модель рүү ЗӨВХӨН БУУЛГАГДАНА, дахин
тооцогдохгүй (AC-1).
"""
from __future__ import annotations

from datetime import timedelta
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


async def test_a_fresh_quote_over_an_hours_old_trade_is_stale():
    """Stop/target нь `last` = сүүлийн ХЭЛЦЭЛ-ийн үнээр буудна. Нимгэн ticker
    дээр market maker quote-оо шинэчилсээр байхад хэлцэл хэвлэгдэхгүй байж
    болно — quote-ын нас л шалгавал хуучирсан үнээр MARKET гарна."""
    from app.util.time import now_utc, to_iso

    now = now_utc()
    payload = {
        "symbol": "THIN",
        "latestQuote": {"bp": "10.00", "ap": "10.20", "t": to_iso(now)},
        "latestTrade": {"p": "10.10", "t": to_iso(now - timedelta(hours=2))},
    }
    adapter = _adapter(lambda r: httpx.Response(200, json=payload))
    env = await adapter.get_quote("THIN")
    assert env.stale is True


async def test_open_orders_ask_for_more_than_alpacas_default_page():
    """`exits.py` үүнийг давхар-зарахаас хамгаалах гарцаа болгон ашиглана.
    Alpaca анхдагчаар 50 мөр буцаадаг, pagination байхгүй — таслагдсан
    жагсаалт нь чимээгүй унтарсан хамгаалалт."""
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json=[])

    adapter = _adapter(handler)
    await adapter.get_open_orders()
    assert int(seen["limit"]) >= 500


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


# --- статус буулгалт: танихгүй статус нь ТЕРМИНАЛ БИШ ---

ORDER_JSON = {
    "id": "brk-1",
    "client_order_id": "p3-live-1",
    "symbol": "AAPL",
    "side": "buy",
    "qty": "10",
    "filled_qty": "0",
    "type": "market",
    "time_in_force": "day",
    "submitted_at": "2026-09-16T14:30:00Z",
}


@pytest.mark.parametrize(
    "status", ["pending_cancel", "pending_replace", "stopped", "calculated", "нэрлээгүй_шинэ"]
)
async def test_an_unmapped_status_never_makes_a_live_order_look_dead(status):
    """`failed` нь `OPEN_STATUSES`-д байхгүй тул exits-ийн давхар-зарах хаалга
    тэр symbol-ыг хамрахаа болино — амьд order дээр нэмж зарна."""
    from app.api.attribution import LIVE_STATUSES
    from app.broker.models import OrderStatus

    adapter = _adapter(lambda r: httpx.Response(200, json=[{**ORDER_JSON, "status": status}]))
    [order] = (await adapter.get_open_orders()).data
    assert order.status is not OrderStatus.FAILED
    assert order.status.value in LIVE_STATUSES


async def test_a_trade_update_with_an_unmapped_status_is_not_terminal_either():
    from app.api.attribution import LIVE_STATUSES

    adapter = _adapter(lambda r: httpx.Response(200, json={}))
    update = adapter.map_trade_update(
        {"event": "pending_cancel", "order": {**ORDER_JSON, "status": "pending_cancel"}}
    )
    assert update.status.value in LIVE_STATUSES


# --- терминал order-ыг нэрээр нь асуух зам (тулгалтын үндэс) ---


async def test_get_order_by_client_id_sees_a_filled_order():
    """`status=open` жагсаалтад БАЙХГҮЙ order — зөвхөн энэ замаар олдоно."""
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen.update(request.url.params)
        return httpx.Response(200, json={**ORDER_JSON, "status": "filled", "filled_qty": "10"})

    adapter = _adapter(handler)
    order = await adapter.get_order_by_client_id("p3-live-1")
    assert seen["path"].endswith(":by_client_order_id")
    assert seen["client_order_id"] == "p3-live-1"
    assert order is not None and order.filled_qty == Decimal("10")


async def test_an_unknown_client_order_id_is_none_not_an_outage():
    """404 = Alpaca ХАРИУЛСАН. Retry ч, `api_error_rate` ч хөдлөхгүй."""
    calls = {"n": 0}
    reported: list[bool] = []

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404, json={"message": "order not found"})

    adapter = _adapter(handler)

    async def reporter(ok: bool) -> None:
        reported.append(ok)

    adapter.bind_api_reporter(reporter)
    assert await adapter.get_order_by_client_id("p3-ghost") is None
    assert calls["n"] == 1
    assert reported == [True]


async def test_a_lookup_outage_is_still_an_outage():
    adapter = _adapter(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(BrokerUnavailable):
        await adapter.get_order_by_client_id("p3-live-1")
