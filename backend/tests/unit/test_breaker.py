"""Circuit breaker-ийн хэмжигдээгүй салаанууд (B-3 · LLD §15, §18.3).

Coverage gate нь `app/risk/**`-ээс 100% line + branch шаарддаг. Өмнө нь
хаалга гурван файлыг НЭРЛЭСЭН тул `breaker.py` хэмжигдэлгүй үлдэж, доорх
гурван салаа тестгүй байв:

1. Broker хүрэхгүй үед P&L-ийг ТААМАГЛАХГҮЙ (halt үүсгэхгүй).
2. `last_equity` байхгүй шинэ данс — мөн адил «хэмжигдээгүй».
3. Метрик унаагүй үед `enforce()` нь төлөвт ХҮРЭХГҮЙ.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.broker.models import SystemState
from app.risk.breaker import DAILY_LOSS, CircuitBreaker
from app.system.state import StateMachine
from tests.fakes import DEFAULT_ACCOUNT


@pytest.fixture
def breaker(db_session, settings, broker):
    return CircuitBreaker(db_session, settings=settings, broker=broker)


async def _daily_loss(breaker) -> object:
    return next(r for r in await breaker.measure() if r.metric == DAILY_LOSS)


async def test_unreachable_broker_does_not_fabricate_a_pnl(breaker, broker):
    """Хүрэхгүй broker нь halt үүсгэхгүй — уналт нь `api_error_rate`-ийн ажил."""
    broker.reachable = False
    reading = await _daily_loss(breaker)
    assert reading.value == "unmeasured"
    assert reading.tripped is False


async def test_account_without_last_equity_is_unmeasured(breaker, broker):
    """Шинэ данс: өмнөх өдрийн equity байхгүй бол зөрүү тооцохгүй."""
    broker.account = dataclasses.replace(DEFAULT_ACCOUNT, last_equity=None)
    reading = await _daily_loss(breaker)
    assert reading.value == "unmeasured"
    assert reading.tripped is False


async def test_enforce_leaves_state_alone_when_nothing_tripped(
    db_session, settings, broker
):
    machine = StateMachine(db_session, wind_down_grace=settings.WIND_DOWN_GRACE)
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="тест")

    breaker = CircuitBreaker(db_session, settings=settings, broker=broker)
    assert await breaker.enforce() is None
    assert (await machine.current()).state is SystemState.ACTIVE
