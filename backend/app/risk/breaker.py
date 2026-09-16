"""Circuit breaker — автомат зогсоолт (T-16, LLD §15, AC-15).

Дөрвөн метрик, тус бүр ДАНГААРАА halt үүсгэнэ. Kill switch-тэй ЯГ ИЖИЛ
төлөвт (`halted`) оруулна — «зөөлөн зогсоолт» гэсэн хоёр дахь горим байхгүй.

**Автомат сэргэх зам БАЙХГҮЙ.** `activate` нь эдгээр метрикийг ДАХИН хэмжинэ:
хадгалагдсан «цэвэрлэсэн» туг байхгүй тул түүнийг гараар асаах замаар
тойрох боломж ч байхгүй (AC-37).

LLM-ээс хамаарал БАЙХГҮЙ — бүх provider унасан үед ч энэ ажиллана.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.broker.models import SystemState
from app.util.money import money_str
from app.util.time import now_utc

DAILY_LOSS = "daily_loss"
API_ERROR_RATE = "api_error_rate"
ORDER_REJECT_RATE = "order_reject_rate"
WS_DISCONNECTS = "ws_disconnects"

METRICS = (DAILY_LOSS, API_ERROR_RATE, ORDER_REJECT_RATE, WS_DISCONNECTS)

#: `breaker_events.kind` → метрик
KIND_FOR = {API_ERROR_RATE: "api_error", ORDER_REJECT_RATE: "order_reject", WS_DISCONNECTS: "ws_disconnect"}


@dataclass(frozen=True, slots=True)
class MetricReading:
    metric: str
    value: str
    limit_name: str
    limit_value: str
    tripped: bool

    def to_json(self) -> dict:
        return {
            "metric": self.metric,
            "value": self.value,
            "limit_name": self.limit_name,
            "limit_value": self.limit_value,
            "tripped": self.tripped,
        }


class CircuitBreaker:
    def __init__(self, session: AsyncSession, *, settings, broker, publisher=None) -> None:
        self.session = session
        self.settings = settings
        self.broker = broker
        self.publisher = publisher

    async def _events(self, kind: str) -> list[models.BreakerEvent]:
        window_start = now_utc() - timedelta(seconds=int(self.settings.BREAKER_WINDOW))
        rows = (
            await self.session.execute(
                select(models.BreakerEvent)
                .where(models.BreakerEvent.kind == kind)
                .where(models.BreakerEvent.ts >= window_start)
            )
        ).scalars().all()
        return list(rows)

    async def _daily_loss(self) -> MetricReading:
        limit = self.settings.DAILY_LOSS_LIMIT
        try:
            account = (await self.broker.get_account()).data
        except Exception:
            # Broker хүрэхгүй бол P&L-ийг ТААМАГЛАХГҮЙ: метрик «хэмжигдээгүй»,
            # тиймээс энэ нь halt үүсгэхгүй. Broker-ийн уналт нь өөрийн
            # метрикээр (api_error_rate) баригдана.
            return MetricReading(DAILY_LOSS, "unmeasured", "DAILY_LOSS_LIMIT", money_str(limit), False)
        if account.last_equity is None:
            return MetricReading(DAILY_LOSS, "unmeasured", "DAILY_LOSS_LIMIT", money_str(limit), False)
        pnl: Decimal = account.equity - account.last_equity
        return MetricReading(
            DAILY_LOSS, money_str(pnl), "DAILY_LOSS_LIMIT", money_str(limit), pnl <= limit
        )

    async def _rate(self, metric: str, limit: Decimal, limit_name: str) -> MetricReading:
        events = await self._events(KIND_FOR[metric])
        total = len(events)
        bad = sum(1 for e in events if not e.ok)
        rate = Decimal(bad) / Decimal(total) if total else Decimal("0")
        return MetricReading(
            metric,
            str(rate.quantize(Decimal("0.0001"))),
            limit_name,
            str(limit),
            total > 0 and rate > limit,
        )

    async def _ws_disconnects(self) -> MetricReading:
        events = await self._events(KIND_FOR[WS_DISCONNECTS])
        count = sum(1 for e in events if not e.ok)
        limit = int(self.settings.WS_DISCONNECT_LIMIT)
        return MetricReading(
            WS_DISCONNECTS, str(count), "WS_DISCONNECT_LIMIT", str(limit), count > limit
        )

    async def measure(self) -> list[MetricReading]:
        return [
            await self._daily_loss(),
            await self._rate(API_ERROR_RATE, self.settings.ERROR_RATE_LIMIT, "ERROR_RATE_LIMIT"),
            await self._rate(ORDER_REJECT_RATE, self.settings.REJECT_RATE_LIMIT, "REJECT_RATE_LIMIT"),
            await self._ws_disconnects(),
        ]

    async def tripped(self) -> list[MetricReading]:
        return [reading for reading in await self.measure() if reading.tripped]

    async def enforce(self) -> list[MetricReading] | None:
        """Monitoring-ийн дуудлага: унасан метрик байвал `halted` руу оруулна."""
        tripped = await self.tripped()
        if not tripped:
            return None
        from app.system.state import StateMachine

        machine = StateMachine(
            self.session,
            wind_down_grace=self.settings.WIND_DOWN_GRACE,
            publisher=self.publisher,
        )
        current = await machine.current()
        if current.state is not SystemState.HALTED:
            await machine.transition(
                SystemState.HALTED,
                by="circuit_breaker",
                reason="; ".join(
                    f"{r.metric}={r.value} vs {r.limit_name}={r.limit_value}" for r in tripped
                ),
            )
        return tripped


async def record(session: AsyncSession, kind: str, ok: bool) -> None:
    """Метрикийн түүхий үйл явдал. Тоолуурыг НЭГ газраас ахиулна."""
    session.add(models.BreakerEvent(kind=kind, ok=ok, ts=now_utc()))
