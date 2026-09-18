"""Paper proving window monitoring (T-39, LLD §22, AC-13).

30+ хоногийн цонх. **Дөрвөн метрик бүгд 0 байх ёстой:**

1. эрсдэлийн хязгаар зөрчсөн тоо (`risk_limit_breach`);
2. order замын барьцаагүй exception (`unhandled_exception`);
3. локал ↔ Alpaca төлөвийн зөрүү (`reconciliation_drift`);
4. grounding алдаа (`grounding_failure`).

**Аль нэг нь > 0 бол тоолуур 0-ЭЭС ДАХИН эхэлнэ.** «30 хоногийн 28 дээр
нэг л асуудал гарсан» гэдэг нь 28 хоног БИШ — нөхцөл нь тасралтгүй цонх.
Эсрэг тохиолдолд цонх нь баталгаа биш, тоолуур болно.

Метрикүүд нь `audit_log`-оос уншигдана: тусдаа тоолуурын хүснэгт үүсгэх нь
хоёр дахь эх сурвалж болно (лог ба тоолуур зөрөх боломж).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.util.time import now_utc, to_iso

#: RELEASE_APPROVAL-ийн нөхцөл (спек §9).
REQUIRED_DAYS = 30

#: `audit_log.event_type` → метрикийн нэр.
FAILURE_EVENTS = {
    "risk_limit_breach": "risk_limit_breach",
    "unhandled_exception": "unhandled_exception",
    "reconciliation_drift": "reconciliation_drift",
    "grounding_failure": "grounding_failure",
}

METRICS = tuple(FAILURE_EVENTS.values())


@dataclass(frozen=True, slots=True)
class Failure:
    metric: str
    at: datetime

    def to_json(self) -> dict:
        return {"metric": self.metric, "at": to_iso(self.at)}


@dataclass(frozen=True, slots=True)
class ProvingWindow:
    """Тайлан. `clean_days` нь СҮҮЛИЙН алдааны ДАРААХ хоног."""

    started_at: datetime
    now: datetime
    failures: list[Failure]
    counts: dict[str, int]

    @property
    def last_failure(self) -> Failure | None:
        return max(self.failures, key=lambda f: f.at) if self.failures else None

    @property
    def window_start(self) -> datetime:
        """Тоолуурын эхлэл: сүүлийн алдааны мөч, эсвэл цонхны эхлэл."""
        last = self.last_failure
        return last.at if last is not None else self.started_at

    @property
    def clean_days(self) -> int:
        return max(0, int((self.now - self.window_start).total_seconds() // 86400))

    @property
    def passed(self) -> bool:
        return self.clean_days >= REQUIRED_DAYS

    def to_json(self) -> dict:
        return {
            "required_days": REQUIRED_DAYS,
            "clean_days": self.clean_days,
            "passed": self.passed,
            "window_start": to_iso(self.window_start),
            "generated_at": to_iso(self.now),
            # Тоолуур нь ТЭГ байх ёстой. Утга нь ил — «ойролцоо» гэж дүгнэхгүй.
            "counts": dict(self.counts),
            "failures": [f.to_json() for f in self.failures],
        }


async def measure(
    session: AsyncSession, *, started_at: datetime | None = None, now: datetime | None = None
) -> ProvingWindow:
    at = now or now_utc()
    start = started_at or (at - timedelta(days=REQUIRED_DAYS))
    rows = list(
        (
            await session.execute(
                select(models.AuditLog)
                .where(models.AuditLog.event_type.in_(tuple(FAILURE_EVENTS)))
                .where(models.AuditLog.ts >= start)
                .order_by(models.AuditLog.ts)
            )
        ).scalars()
    )
    failures = [Failure(FAILURE_EVENTS[row.event_type], row.ts) for row in rows]
    counts = {metric: 0 for metric in METRICS}
    for failure in failures:
        counts[failure.metric] += 1
    return ProvingWindow(started_at=start, now=at, failures=failures, counts=counts)
