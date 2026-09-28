"""`MarketDataIngestor` — tick -> `ticks:{symbol}` (T-99, хувийн төсөл)."""
from __future__ import annotations

from decimal import Decimal

from app.broker.models import Tick
from app.stream.bus import CHANNEL_TICKS, EventBus
from app.stream.ingest import MarketDataIngestor, StalenessMonitor
from app.util.time import now_utc


async def _ticks(*rows):
    for symbol, price in rows:
        yield Tick(symbol=symbol, price=Decimal(price), ts=now_utc())


async def test_consume_publishes_a_normalized_symbol_and_touches_staleness():
    bus = EventBus()
    sub = bus.subscribe([CHANNEL_TICKS])
    monitor = StalenessMonitor(bus, stale_after_seconds=5)
    ingestor = MarketDataIngestor(None, None, bus, monitor, ["BTC/USD"])

    count = await ingestor.consume(_ticks(("BTC/USD", "84123.45")))

    assert count == 1
    message = sub.drain()[0]
    assert message.channel == f"{CHANNEL_TICKS}:BTCUSD"
    assert message.payload["symbol"] == "BTCUSD"
    assert message.payload["price"] == "84123.45"
    assert monitor.track(CHANNEL_TICKS).last_update_at is not None
