"""Alpaca WS ingestion + staleness (T-09, LLD §12, AC-2).

Хоёр урсгал, нэг дүрэм: **чимээгүй тасалдал бол хамгийн аюултай хэлбэр.**
Сүлжээ унтарсан ч `onclose` ирэхгүй тохиолдол байдаг тул тасалдлыг
холболтын үйл явдлаар БИШ, *сүүлийн мессежийн цагаар* илрүүлнэ.

- `StalenessMonitor` — суваг тутмын сүүлийн шинэчлэлтийн UTC цаг. Босго
  давбал `system` сувгаар `stream_stale` нийтэлнэ; дахин мессеж ирэхэд
  `stream_live`. Шилжилт бүр НЭГ УДАА нийтлэгдэнэ — banner анивчихгүй.
- `TradeUpdateIngestor` — Alpaca-ийн trade update → локал `orders`/`fills`.
  Тоон утга бүр Alpaca-аас; ЛОКАЛ ТООЦОО БАЙХГҮЙ (AC-1).

Тасалдал бүр `breaker_events`-д `ws_disconnect` болж бичигдэнэ: circuit
breaker-ийн дөрөв дэх метрик энэ тоолуураас уншина (LLD §15.2).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.broker.models import OrderStatus, TradeUpdate
from app.risk import breaker
from app.stream.bus import CHANNEL_ORDERS, CHANNEL_SYSTEM, EventBus
from app.util.time import now_utc, to_iso

#: Дахин холбогдох хүлээлт: 0.5s → 1s → 2s → … дээд хязгаартай.
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_MAX_SECONDS = 30.0

#: Alpaca-ийн статусаас «биелэлт» гэж үзэх нь.
FILL_EVENTS = ("fill", "partial_fill")


def backoff_delay(attempt: int) -> float:
    """Exponential backoff. `attempt` нь 0-оос эхэлнэ."""
    return min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2**attempt))


@dataclass(slots=True)
class ChannelHealth:
    last_update_at: datetime | None = None
    stale: bool = True


class StalenessMonitor:
    """Суваг тутмын шинэлэг байдал.

    Анхны төлөв нь `stale=True`: мессеж ирээгүй суваг нь «хэвийн» БИШ.
    «Би юу ч аваагүй тул бүх юм хэвийн» гэсэн таамаглал нь яг тэр цонх.
    """

    def __init__(self, bus: EventBus, *, stale_after_seconds: int) -> None:
        self.bus = bus
        self.stale_after_seconds = stale_after_seconds
        self.channels: dict[str, ChannelHealth] = {}

    def track(self, channel: str) -> ChannelHealth:
        return self.channels.setdefault(channel, ChannelHealth())

    def touch(self, channel: str, *, at: datetime | None = None) -> None:
        health = self.track(channel)
        health.last_update_at = at or now_utc()

    async def sweep(self, *, at: datetime | None = None) -> list[tuple[str, bool]]:
        """Төлөв ӨӨРЧЛӨГДСӨН сувгуудыг нийтэлж, жагсаалтыг буцаана."""
        now = at or now_utc()
        changed: list[tuple[str, bool]] = []
        for channel, health in self.channels.items():
            stale = (
                health.last_update_at is None
                or (now - health.last_update_at).total_seconds() > self.stale_after_seconds
            )
            if stale == health.stale:
                continue
            health.stale = stale
            changed.append((channel, stale))
            await self.bus.publish(
                CHANNEL_SYSTEM,
                {
                    "event": "stream_stale" if stale else "stream_live",
                    "channel": channel,
                    "stale": stale,
                    "last_update_at": to_iso(health.last_update_at),
                    "threshold_seconds": self.stale_after_seconds,
                },
            )
        return changed


class TradeUpdateIngestor:
    """Alpaca trade update → локал `orders` / `fills` → bus.

    Локал мөргүй `client_order_id` нь **алдаа биш**: Alpaca UI-аас гараар
    нээсэн order байж болно. Тэр тохиолдолд локал мөр ҮҮСГЭХГҮЙ — attribution
    түүнийг `external` гэж үзнэ (LLD §11.1). Мөр зохиох нь худал гарал үүсэл.
    """

    def __init__(
        self,
        sessionmaker,
        broker,
        bus: EventBus,
        monitor: StalenessMonitor,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.broker = broker
        self.bus = bus
        self.monitor = monitor

    async def apply(self, session: AsyncSession, update: TradeUpdate) -> models.Order | None:
        row = (
            await session.execute(
                select(models.Order).where(
                    models.Order.client_order_id == update.client_order_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None

        row.status = update.status.value
        row.filled_qty = update.filled_qty
        if row.broker_order_id is None:
            row.broker_order_id = update.broker_order_id
        if update.status is OrderStatus.FILLED and row.filled_at is None:
            row.filled_at = update.ts

        if update.event in FILL_EVENTS and update.filled_avg_price is not None:
            await self._record_fill(session, row, update)

        # Reject-ийн түвшин нь breaker-ийн метрик (LLD §15.2).
        if update.status in (OrderStatus.REJECTED, OrderStatus.FAILED):
            await breaker.record(session, "order_reject", ok=False)
        elif update.status in (OrderStatus.ACCEPTED, OrderStatus.FILLED):
            await breaker.record(session, "order_reject", ok=True)

        await session.commit()
        return row

    async def _record_fill(
        self, session: AsyncSession, row: models.Order, update: TradeUpdate
    ) -> None:
        fill_id = str(update.raw.get("execution_id") or f"{update.broker_order_id}:{update.ts}")
        existing = (
            await session.execute(
                select(models.Fill).where(models.Fill.broker_fill_id == fill_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return  # WS дахин холбогдоход ижил үйл явдал давтагдаж болно
        session.add(
            models.Fill(
                order_id=row.id,
                broker_fill_id=fill_id,
                qty=update.filled_qty,
                # AC-1: Alpaca-ийн мэдээлсэн үнэ. qty × price ХЭЗЭЭ Ч энд биш.
                price=update.filled_avg_price or Decimal("0"),
                filled_at=update.ts,
                raw=update.raw,
            )
        )

    async def consume(self, stream) -> int:
        """Нэг холболтын мөчлөг. Урсгал дуусахад тоог буцаана."""
        count = 0
        async for update in stream:
            self.monitor.touch(CHANNEL_ORDERS, at=update.ts)
            async with self.sessionmaker() as session:
                row = await self.apply(session, update)
                payload = {
                    "event": "trade_update",
                    "client_order_id": update.client_order_id,
                    "broker_order_id": update.broker_order_id,
                    "status": update.status.value,
                    "filled_qty": str(update.filled_qty),
                    "ts": to_iso(update.ts),
                    # Локал мөргүй бол ил хэлнэ — UI үүнийг `external` гэж үзнэ.
                    "known_locally": row is not None,
                }
            await self.bus.publish(CHANNEL_ORDERS, payload)
            count += 1
        return count

    async def run_forever(self, *, max_cycles: int | None = None) -> int:
        """Дахин холболт exponential backoff-той.

        Тасалдал бүр `ws_disconnect` болж бичигдэнэ. `max_cycles` нь тестэд —
        prod-д `None` (хязгааргүй).
        """
        attempt = 0
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            cycles += 1
            try:
                await self.consume(self.broker.stream_trade_updates())
                attempt = 0
            except Exception:
                async with self.sessionmaker() as session:
                    await breaker.record(session, "ws_disconnect", ok=False)
                    await session.commit()
            await self.monitor.sweep()
            await asyncio.sleep(backoff_delay(attempt))
            attempt += 1
        return cycles
