"""Давтамжит ажлууд (LLD §6.4, §15.2, §15.3, §7-ийн EOD).

Дөрвөн job, дөрвөн өөр давтамж. Бүгд **идемпотент**: давхар ажиллах нь
хоёр дахин үр дагавар үүсгэхгүй. Тиймээс process хоёр хувилбараар
ажиллаж эхлэх нь өгөгдлийг эвдэхгүй.

| Job | Давтамж | Юу хийдэг |
|---|---|---|
| `sweep_grace`   | 10s | wind-down-ийн grace дуусахад `halted` |
| `expire_approvals` | 30s | TTL дууссан approval → `expired` |
| `enforce_breaker`  | 5s | дөрвөн метрик; босго давбал `halted` |
| `reconcile_eod`    | өдөрт 1 | Alpaca ↔ локал тулгалт |

APScheduler-ийг ЭНД л мэднэ: бусад модуль цэвэр async функц хэвээр тул
тест нь scheduler-гүйгээр шууд дуудна.
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

GRACE_SWEEP_SECONDS = 10
APPROVAL_REAP_SECONDS = 30
BREAKER_SECONDS = 5
#: Зах зээл хаагдсаны дараа (US/Eastern 16:00 → UTC 21:00 өвөл, 20:00 зун).
#: Цагийн бүсийн шилжилтэд найдахгүй: UTC 22:00 нь хоёуланд нь хаалтын дараа.
EOD_HOUR_UTC = 22


async def sweep_grace(sessionmaker, settings, publisher) -> None:
    from app.system.state import StateMachine

    async with sessionmaker() as session:
        await StateMachine(
            session, wind_down_grace=settings.WIND_DOWN_GRACE, publisher=publisher
        ).sweep_expired_grace()


async def expire_approvals(sessionmaker) -> int:
    from app.approvals.reaper import expire_due

    async with sessionmaker() as session:
        return await expire_due(session)


async def enforce_breaker(sessionmaker, settings, broker, publisher):
    from app.risk.breaker import CircuitBreaker

    async with sessionmaker() as session:
        return await CircuitBreaker(
            session, settings=settings, broker=broker, publisher=publisher
        ).enforce()


async def reconcile_eod(sessionmaker, settings, broker, publisher):
    from app.broker.reconcile import reconcile

    async with sessionmaker() as session:
        return await reconcile(session, broker, settings=settings, publisher=publisher)


def schedule_wind_down_deadline(app, deadline) -> None:
    """Grace дуусах ЯГ агшинд ажиллах нэг удаагийн job (LLD §6.4, D-8).

    10 секундын `interval` sweep дангаараа ±10s нарийвчлалтай — kill
    switch-ийн амлалт нь «цонх» биш, «агшин». `date` job нь тэр агшныг
    барина; `interval` нь job алдагдсан (restart) үеийн нөөц хэвээр.
    """
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None or deadline is None:
        return
    scheduler.add_job(
        sweep_grace,
        DateTrigger(run_date=deadline),
        args=[app.state.sessionmaker, app.state.settings, app.state.publish_system],
        id="wind_down_deadline",
        replace_existing=True,
    )


def build_scheduler(app) -> AsyncIOScheduler:
    """`app.state`-аас хамаарлаа авна — глобал синглтон БАЙХГҮЙ."""
    sessionmaker = app.state.sessionmaker
    settings = app.state.settings
    broker = app.state.broker
    publisher = app.state.publish_system

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        sweep_grace, "interval", seconds=GRACE_SWEEP_SECONDS,
        args=[sessionmaker, settings, publisher], id="sweep_grace",
    )
    scheduler.add_job(
        expire_approvals, "interval", seconds=APPROVAL_REAP_SECONDS,
        args=[sessionmaker], id="expire_approvals",
    )
    # `max_instances`/`coalesce` нь ИЛ: broker удаашрахад ажиллалт хуримтлах
    # эсвэл давхцахгүй. Дуудлагын хугацааг `breaker.BROKER_PROBE_TIMEOUT`
    # хязгаарладаг тул энэ нь зөвхөн хамгаалалтын хоёр дахь давхарга (O-1).
    scheduler.add_job(
        enforce_breaker, "interval", seconds=BREAKER_SECONDS,
        args=[sessionmaker, settings, broker, publisher], id="enforce_breaker",
        max_instances=1, coalesce=True, misfire_grace_time=BREAKER_SECONDS,
    )
    scheduler.add_job(
        reconcile_eod, CronTrigger(hour=EOD_HOUR_UTC, minute=0, timezone="UTC"),
        args=[sessionmaker, settings, broker, publisher], id="reconcile_eod",
    )
    return scheduler
