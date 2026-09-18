"""`BrokerPort` (LLD §7).

`submit_order`-ийн оролт нь **`ValidatedOrder`** — `ManualOrderRequest` ч,
`ProposedOrder` ч биш. `ValidatedOrder`-ыг үүсгэх ЦОРЫН ГАНЦ газар нь
`risk.agent.evaluate()`-ийн `APPROVE` салаа. Risk-ийг тойрсон дуудагч нь
тохирох объектыг гартаа авч чадахгүй — P-1-ийг ТӨРЛИЙН системээр барина.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.broker.models import (
    Account,
    BrokerOrder,
    Envelope,
    Position,
    Quote,
    Tick,
    TradeUpdate,
    ValidatedOrder,
)


@runtime_checkable
class BrokerPort(Protocol):
    async def get_account(self) -> Envelope[Account]: ...

    async def get_positions(self) -> Envelope[list[Position]]: ...

    async def get_open_orders(self) -> Envelope[list[BrokerOrder]]: ...

    async def get_quote(self, symbol: str) -> Envelope[Quote]: ...

    async def submit_order(self, req: ValidatedOrder) -> BrokerOrder: ...

    async def cancel_order(self, broker_order_id: str) -> None: ...

    def stream_market_data(self, symbols: list[str]) -> AsyncIterator[Tick]: ...

    def stream_trade_updates(self) -> AsyncIterator[TradeUpdate]: ...
