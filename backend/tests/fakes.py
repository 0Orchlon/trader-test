"""Тестийн хуурамч broker / provider-ууд.

Alpaca руу ХЭЗЭЭ Ч хүрэхгүй — `LiveEgressGuard` нь сүлжээний талаас, эдгээр нь
логикийн талаас. Хуурамч нь `BrokerPort`-ийн ЯГ гэрээг л биелүүлнэ: илүү
талбар нэмэх, дутуу буцаах нь тестийг бодит байдлаас салгана.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

from app.broker.models import (
    Account,
    BrokerOrder,
    BrokerUnavailable,
    Envelope,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    Quote,
    Source,
    SystemState,
    Tick,
    TimeInForce,
    TradeUpdate,
    ValidatedOrder,
)
from app.util.time import now_utc

DEFAULT_ACCOUNT = Account(
    account_id="PA3X9QK2TLZ0",
    equity=Decimal("104238.17"),
    cash=Decimal("38210.55"),
    buying_power=Decimal("76421.10"),
    last_equity=Decimal("103980.44"),
    pattern_day_trader=False,
    day_trade_count=1,
    trading_blocked=False,
)


class FakeBroker:
    """`BrokerPort`-ийн тестийн хэрэгжүүлэлт — дуудалт бүрийг тоолно."""

    def __init__(
        self,
        *,
        account: Account | None = None,
        positions: list[Position] | None = None,
        open_orders: list[BrokerOrder] | None = None,
        quotes: dict[str, Quote] | None = None,
        source: Source = Source.ALPACA_PAPER,
    ) -> None:
        self.account = account or DEFAULT_ACCOUNT
        self.positions = positions or []
        self.open_orders = open_orders or []
        self.quotes = quotes or {}
        self.source = source
        self.submitted: list[ValidatedOrder] = []
        self.canceled: list[str] = []
        #: Дуудагдсан методын дараалал — «Alpaca руу 0 дуудалт» гэдгийг
        #: submit-ээр БИШ, бүх гадаргуугаар шалгана (AC-33).
        self.calls: list[str] = []
        self.fail_submit: Exception | None = None
        self.reachable = True
        self.stale = False
        self._system_state = SystemState.ACTIVE

    def bind_system_state(self, provider) -> None:
        self._provider = provider

    @property
    def system_state(self) -> SystemState:
        provider = getattr(self, "_provider", None)
        return provider() if provider else self._system_state

    def _envelope(self, data) -> Envelope:
        if not self.reachable:
            raise BrokerUnavailable("тестийн broker унтраалттай")
        return Envelope(
            data=data,
            source=self.source,
            as_of=now_utc(),
            stale=self.stale,
            system_state=self.system_state,
        )

    async def get_account(self) -> Envelope[Account]:
        self.calls.append("get_account")
        return self._envelope(self.account)

    async def get_positions(self) -> Envelope[list[Position]]:
        self.calls.append("get_positions")
        return self._envelope(list(self.positions))

    async def get_open_orders(self) -> Envelope[list[BrokerOrder]]:
        self.calls.append("get_open_orders")
        return self._envelope(list(self.open_orders))

    async def get_quote(self, symbol: str) -> Envelope[Quote]:
        self.calls.append(f"get_quote:{symbol}")
        if symbol not in self.quotes:
            raise BrokerUnavailable(f"{symbol}: quote байхгүй")
        return self._envelope(self.quotes[symbol])

    async def submit_order(self, req: ValidatedOrder) -> BrokerOrder:
        self.calls.append("submit_order")
        if self.fail_submit is not None:
            raise self.fail_submit
        self.submitted.append(req)
        return BrokerOrder(
            broker_order_id=f"brk-{len(self.submitted)}",
            client_order_id=req.client_order_id,
            symbol=req.symbol,
            side=req.side,
            qty=req.qty,
            filled_qty=Decimal("0"),
            order_type=req.order_type,
            time_in_force=req.time_in_force,
            status=OrderStatus.ACCEPTED,
            submitted_at=now_utc(),
        )

    async def cancel_order(self, broker_order_id: str) -> None:
        self.calls.append("cancel_order")
        self.canceled.append(broker_order_id)

    async def stream_market_data(self, symbols: list[str]) -> AsyncIterator[Tick]:
        for symbol in symbols:  # pragma: no cover - тестэд ашиглагдаагүй
            yield Tick(symbol=symbol, price=Decimal("1"), ts=now_utc())

    async def stream_trade_updates(self) -> AsyncIterator[TradeUpdate]:
        return
        yield  # pragma: no cover


def quote(symbol: str, last: str) -> Quote:
    price = Decimal(last)
    return Quote(
        symbol=symbol,
        bid=price,
        ask=price,
        last=price,
        quote_ts=now_utc(),
    )


def position(symbol: str, qty: str, market_value: str, side: PositionSide = PositionSide.LONG):
    return Position(
        symbol=symbol,
        qty=Decimal(qty),
        side=side,
        avg_entry_price=Decimal("100.00"),
        market_value=Decimal(market_value),
        unrealized_pl=Decimal("0.00"),
    )


def broker_order(client_order_id: str, symbol: str = "AAPL") -> BrokerOrder:
    return BrokerOrder(
        broker_order_id="brk-x",
        client_order_id=client_order_id,
        symbol=symbol,
        side=OrderSide.BUY,
        qty=Decimal("1"),
        filled_qty=Decimal("0"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        status=OrderStatus.ACCEPTED,
        submitted_at=now_utc(),
    )


class FakeWebSocket:
    """Alpaca-ийн `/stream` сокетын оронд. Явуулсан бүхнийг тэмдэглэнэ."""

    def __init__(self, frames) -> None:
        self.frames = list(frames)
        self.sent: list[dict] = []
        self.closed = False

    async def send(self, payload) -> None:
        import json

        self.sent.append(json.loads(payload))

    def __aiter__(self):
        return self._frames()

    async def _frames(self):
        for frame in self.frames:
            yield frame


def fake_ws_connect(frames):
    """`(socket, connect)` — `connect(url)` нь async context manager."""
    socket = FakeWebSocket(frames)
    urls: list[str] = []

    class _Connect:
        def __init__(self, url, **kwargs) -> None:
            urls.append(url)

        async def __aenter__(self):
            return socket

        async def __aexit__(self, *exc):
            socket.closed = True
            return False

    socket.urls = urls
    return socket, _Connect
