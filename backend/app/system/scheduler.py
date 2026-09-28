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
| `run_research_cycle` | `RESEARCH_INTERVAL_SECONDS` | автономи LLM мөчлөг (T-99, хувийн төсөл) |
| `snapshot_equity` | `EQUITY_SNAPSHOT_SECONDS` | equity-ийн бодит түүврийг хадгална (T-99, хувийн төсөл) |
| `run_exits` | `EXIT_CHECK_SECONDS` | stop/target/max-hold хаалт (T-99, хувийн төсөл) |
| `run_manual_take_profit` | `MANUAL_TAKE_PROFIT_CHECK_SECONDS` | гар позицийг ашигтай болмогц авто-хаах toggle (T-99, хувийн төсөл) |

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


async def run_research_cycle(sessionmaker, settings, broker, publisher, provider_router, bus) -> None:
    """T-99 (хувийн төсөл, LLD-д тусгаагүй) — автономи LLM decision cycle."""
    from app.agents.runner import run_research_cycle as _run_research_cycle

    await _run_research_cycle(sessionmaker, settings, broker, publisher, provider_router, bus)


async def run_exits(sessionmaker, settings, broker, publisher) -> None:
    """T-99 (хувийн төсөл) — stop-loss / take-profit / max-hold хаалт."""
    from app.execution.exits import run_exits as _run_exits

    await _run_exits(sessionmaker, settings, broker, publisher)


async def run_manual_take_profit(sessionmaker, settings, broker, publisher) -> None:
    """T-99 (хувийн төсөл) — гар позицийг ашигтай болмогц авто-хаах toggle."""
    from app.execution.manual_take_profit import run_manual_take_profit as _run

    await _run(sessionmaker, settings, broker, publisher)


async def snapshot_equity(sessionmaker, broker) -> None:
    """T-99 (хувийн төсөл) — dashboard-ийн минут тутмын graph-ийн эх сурвалж.

    Broker унасан бол алгасна: хуучин утгыг ХЭЗЭЭ Ч давтаж бичихгүй
    («кэшээс хуучин утга» гэдэг хэлбэрийн зөрчлөөс сэргийлнэ, LLD §7).
    """
    from app import models
    from app.broker.models import BrokerUnavailable
    from app.util.time import now_utc

    try:
        account = (await broker.get_account()).data
    except BrokerUnavailable:
        return
    async with sessionmaker() as session:
        session.add(models.EquitySnapshot(equity=account.equity, cash=account.cash, ts=now_utc()))
        await session.commit()


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
    scheduler.add_job(
        run_research_cycle, "interval", seconds=settings.RESEARCH_INTERVAL_SECONDS,
        args=[sessionmaker, settings, broker, publisher, app.state.provider_router, app.state.bus],
        id="run_research_cycle", max_instances=1, coalesce=True,
        misfire_grace_time=settings.RESEARCH_INTERVAL_SECONDS,
    )
    scheduler.add_job(
        run_exits, "interval", seconds=settings.EXIT_CHECK_SECONDS,
        args=[sessionmaker, settings, broker, publisher], id="run_exits",
        max_instances=1, coalesce=True, misfire_grace_time=settings.EXIT_CHECK_SECONDS,
    )
    scheduler.add_job(
        snapshot_equity, "interval", seconds=settings.EQUITY_SNAPSHOT_SECONDS,
        args=[sessionmaker, broker], id="snapshot_equity",
        max_instances=1, coalesce=True, misfire_grace_time=settings.EQUITY_SNAPSHOT_SECONDS,
    )
    scheduler.add_job(
        run_manual_take_profit, "interval", seconds=settings.MANUAL_TAKE_PROFIT_CHECK_SECONDS,
        args=[sessionmaker, settings, broker, publisher], id="run_manual_take_profit",
        max_instances=1, coalesce=True, misfire_grace_time=settings.MANUAL_TAKE_PROFIT_CHECK_SECONDS,
    )
    return scheduler
