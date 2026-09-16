"""T-04 — Event bus + WS fan-out (AC-2, AC-14).

Голлох дүрэм: `system` суваг ХЭЗЭЭ Ч хаягдахгүй. `ticks` нь backpressure дор
хаягдаж болно. Тест нь 10 000 tick-ээр дүүргээд `system` мессеж хүрсэн эсэхийг
шалгана — «ачаалал дор алдагдсан kill switch» нь чимээгүй уналт.
"""
from __future__ import annotations

import asyncio

import pytest

from app.stream.bus import CHANNEL_SYSTEM, CHANNEL_TICKS, EventBus, Subscriber


async def test_system_message_survives_tick_flood():
    bus = EventBus(tick_buffer=16)
    sub = bus.subscribe(["ticks:AAPL", CHANNEL_SYSTEM])

    for i in range(10_000):
        await bus.publish(f"{CHANNEL_TICKS}:AAPL", {"symbol": "AAPL", "price": str(i)})
    await bus.publish(CHANNEL_SYSTEM, {"event": "kill_switch_engaged"})

    drained = sub.drain()
    system_events = [m for m in drained if m.channel == CHANNEL_SYSTEM]
    assert len(system_events) == 1
    assert system_events[0].payload["event"] == "kill_switch_engaged"
    # Backpressure бодлого: tick хаягдсан байх ЁСТОЙ (буфер 16).
    ticks = [m for m in drained if m.channel.startswith(CHANNEL_TICKS)]
    assert len(ticks) <= 16
    assert bus.dropped > 0


async def test_every_message_carries_monotonic_seq():
    bus = EventBus()
    sub = bus.subscribe([CHANNEL_SYSTEM])
    await bus.publish(CHANNEL_SYSTEM, {"event": "heartbeat"})
    await bus.publish(CHANNEL_SYSTEM, {"event": "heartbeat"})
    seqs = [m.payload["seq"] for m in sub.drain()]
    assert seqs == sorted(seqs) and len(set(seqs)) == 2


async def test_subscriber_only_receives_subscribed_channels():
    bus = EventBus()
    sub = bus.subscribe([CHANNEL_SYSTEM])
    await bus.publish(f"{CHANNEL_TICKS}:AAPL", {"symbol": "AAPL"})
    assert sub.drain() == []


async def test_reconnect_resends_state_snapshot():
    """AC-14 DoD (б): клиент дахин холбогдоход төлөв дахин илгээгдэнэ."""
    bus = EventBus()
    await bus.publish(CHANNEL_SYSTEM, {"event": "state_changed", "state": "halted"})
    fresh = bus.subscribe([CHANNEL_SYSTEM], replay_system=True)
    replayed = fresh.drain()
    assert [m.payload["state"] for m in replayed] == ["halted"]


async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    sub = bus.subscribe([CHANNEL_SYSTEM])
    bus.unsubscribe(sub)
    await bus.publish(CHANNEL_SYSTEM, {"event": "heartbeat"})
    assert sub.drain() == []


async def test_await_message_wakes_on_publish():
    bus = EventBus()
    sub: Subscriber = bus.subscribe([CHANNEL_SYSTEM])
    task = asyncio.create_task(sub.get())
    await asyncio.sleep(0)
    await bus.publish(CHANNEL_SYSTEM, {"event": "heartbeat"})
    message = await asyncio.wait_for(task, timeout=1.0)
    assert message.payload["event"] == "heartbeat"


async def test_redis_backend_publishes_through_same_interface():
    """REDIS_URL тохируулсан үед bus нь Redis рүү давхар нийтэлнэ."""
    published: list[tuple[str, str]] = []

    class FakeRedis:
        async def publish(self, channel: str, data: str) -> None:
            published.append((channel, data))

    bus = EventBus(redis=FakeRedis())
    await bus.publish(CHANNEL_SYSTEM, {"event": "heartbeat"})
    assert published and published[0][0] == CHANNEL_SYSTEM


@pytest.mark.parametrize("channel", ["orders", "agent-decisions"])
async def test_ordered_channels_are_not_dropped(channel: str):
    """`orders` ба `agent-decisions` нь дарааллаараа хадгалагдана (asyncapi)."""
    bus = EventBus(tick_buffer=4)
    sub = bus.subscribe([channel])
    for i in range(500):
        await bus.publish(channel, {"i": i})
    received = [m.payload["i"] for m in sub.drain()]
    assert received == list(range(500))
