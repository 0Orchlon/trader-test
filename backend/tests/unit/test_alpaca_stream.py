"""`AlpacaAdapter.stream_trade_updates()` — бодит `/stream` WS (LLD §12, AC-2).

UAT 5-р тойргийн блоклогч: метод нь `NotImplementedError` гаргадаг байв.
`TradeUpdateIngestor.run_forever()` түүнийг мөнхийн давталтад дуудаж,
уналт бүрт `ws_disconnect` бичдэг тул тоолуур хязгааргүй өсч
`POST /system/activate` үргэлж 409 `breaker_still_tripped` буцаана —
байршуулсан систем `halted`-аас ХЭЗЭЭ Ч гарч чадахгүй.

Alpaca-ийн протокол (docs «Websocket Streaming»):
1. `wss://{host}/stream` руу холбогдоно.
2. `{"action":"auth","key":…,"secret":…}` → `authorization`/`authorized`.
3. `{"action":"listen","data":{"streams":["trade_updates"]}}` → `listening`.
4. `{"stream":"trade_updates","data":{…}}` — paper нь ДУУДЛАГА frame-ийг
   binary-ээр илгээдэг тул bytes ч, str ч ирж болно.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.broker.alpaca import AlpacaAdapter
from app.broker.models import BrokerUnavailable, OrderStatus
from app.config.mode import TradingMode
from tests.fakes import fake_ws_connect

AUTH_OK = {"stream": "authorization", "data": {"status": "authorized", "action": "authenticate"}}
AUTH_BAD = {"stream": "authorization", "data": {"status": "unauthorized", "action": "authenticate"}}
LISTENING = {"stream": "listening", "data": {"streams": ["trade_updates"]}}
SERVER_ERROR = {"action": "error", "data": {"error_message": "internal server error"}}

FILL = {
    "stream": "trade_updates",
    "data": {
        "event": "fill",
        "execution_id": "2f63ea93-423d-4169-b3f6-3fdafc10c418",
        "price": "221.44",
        "qty": "10",
        "position_qty": "10",
        "timestamp": "2026-09-17T14:30:05.024916Z",
        "order": {
            "id": "a5be8f5e-fdfa-41f5-a644-7a74fe947a8f",
            "client_order_id": "p3-seed-manual",
            "symbol": "AAPL",
            "side": "buy",
            "qty": "10",
            "filled_qty": "10",
            # AC-1: дундаж үнэ Alpaca-аас. `price × qty` ХЭЗЭЭ Ч тооцогдохгүй.
            "filled_avg_price": "221.44",
            "status": "filled",
            "type": "limit",
            "time_in_force": "day",
            "submitted_at": "2026-09-17T14:30:04.980944Z",
            "filled_at": "2026-09-17T14:30:05.024916Z",
        },
    },
}


def _adapter(connect, *, mode=TradingMode.PAPER, key="k", secret="s") -> AlpacaAdapter:
    return AlpacaAdapter(mode=mode, api_key=key, api_secret=secret, ws_connect=connect)


async def test_stream_authenticates_listens_and_maps_the_fill():
    socket, connect = fake_ws_connect(
        [json.dumps(AUTH_OK), json.dumps(LISTENING), json.dumps(FILL).encode()]
    )
    adapter = _adapter(connect)

    updates = [update async for update in adapter.stream_trade_updates()]

    assert socket.urls == ["wss://paper-api.alpaca.markets/stream"]
    assert socket.sent == [
        {"action": "auth", "key": "k", "secret": "s"},
        {"action": "listen", "data": {"streams": ["trade_updates"]}},
    ]
    assert len(updates) == 1
    assert updates[0].event == "fill"
    assert updates[0].client_order_id == "p3-seed-manual"
    assert updates[0].status is OrderStatus.FILLED
    assert updates[0].filled_qty == Decimal("10")
    assert updates[0].filled_avg_price == Decimal("221.44")
    assert updates[0].raw["execution_id"] == "2f63ea93-423d-4169-b3f6-3fdafc10c418"
    # Урсгал дуусахад холболт ХААГДАНА — нөөц алдагдахгүй.
    assert socket.closed is True


async def test_unauthorized_is_an_error_not_a_silent_idle_connection():
    """Буруу түлхүүрээр «чимээгүй хүлээх» нь хамгийн аюултай хэлбэр."""
    socket, connect = fake_ws_connect([json.dumps(AUTH_BAD)])
    adapter = _adapter(connect)
    with pytest.raises(BrokerUnavailable, match="authorization"):
        async for _ in adapter.stream_trade_updates():
            pass  # pragma: no cover
    assert socket.closed is True


async def test_server_error_frame_raises():
    _, connect = fake_ws_connect([json.dumps(AUTH_OK), json.dumps(SERVER_ERROR)])
    adapter = _adapter(connect)
    with pytest.raises(BrokerUnavailable, match="internal server error"):
        async for _ in adapter.stream_trade_updates():
            pass  # pragma: no cover


async def test_missing_credentials_never_open_a_socket():
    socket, connect = fake_ws_connect([json.dumps(AUTH_OK)])
    adapter = _adapter(connect, key=None, secret=None)
    with pytest.raises(BrokerUnavailable, match="түлхүүр"):
        async for _ in adapter.stream_trade_updates():
            pass  # pragma: no cover
    assert socket.urls == []


async def test_live_stream_host_is_blocked_inside_tests(_live_egress_guard):
    """AC-12 — WS зам нь REST-ийн адил egress хаалгаар дайрна."""
    from app.config.egress import LiveEgressViolation

    socket, connect = fake_ws_connect([json.dumps(AUTH_OK)])
    adapter = _adapter(connect, mode=TradingMode.LIVE)
    with pytest.raises(LiveEgressViolation):
        async for _ in adapter.stream_trade_updates():
            pass  # pragma: no cover
    assert socket.urls == []
    assert _live_egress_guard.blocked  # барьсан
    _live_egress_guard.blocked.clear()  # энэ тест зориудаар оролдсон


async def test_non_trade_update_streams_are_ignored_not_guessed():
    """`listening`/`authorization` нь арилжааны үйл явдал БИШ."""
    _, connect = fake_ws_connect(
        [json.dumps(AUTH_OK), json.dumps(LISTENING), json.dumps({"stream": "other", "data": {}})]
    )
    adapter = _adapter(connect)
    assert [u async for u in adapter.stream_trade_updates()] == []
