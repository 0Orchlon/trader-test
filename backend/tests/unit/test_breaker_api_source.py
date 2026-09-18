"""`api_error_rate` метрикийн ҮЙЛДВЭРЛЭЛИЙН эх сурвалж (B-1 · LLD §15.2, AC-15).

Өмнө нь `breaker_events`-ийн `api_error` мөрийг ЗӨВХӨН тест нэмдэг байв:
`AlpacaAdapter`-ийн бүх REST салаа `BrokerUnavailable` шидээд өнгөрдөг тул
тоолуур хөдөлгүй, `_rate()` нь хоосон цонхыг `0.0000 · унаагүй` гэж НОГООН
харуулдаг байсан. Alpaca бүрэн унасан үед дөрвөн метрикийн аль нь ч унахгүй
цонх үүснэ.

Гурван шалгуур:
1. REST дуудалт бүр (амжилттай ба амжилтгүй) тоолуурт бүртгэгдэнэ.
2. Хэмжилтгүй цонх нь `0.0000` БИШ, `unmeasured` гэж ил гарна.
3. Broker бүрэн унахад `api_error_rate` ДАНГААРАА `halted` үүсгэнэ.
"""
from __future__ import annotations

import httpx
import pytest

from app.broker.alpaca import AlpacaAdapter
from app.broker.models import BrokerUnavailable, OrderSide, OrderType, SystemState, TimeInForce, ValidatedOrder
from app.config.mode import TradingMode
from app.risk import breaker as breaker_mod
from app.risk.breaker import API_ERROR_RATE, CircuitBreaker
from app.system.state import StateMachine
from tests.unit.test_alpaca_adapter import ACCOUNT_JSON

from decimal import Decimal


def _adapter(handler) -> tuple[AlpacaAdapter, list[bool]]:
    seen: list[bool] = []

    async def reporter(ok: bool) -> None:
        seen.append(ok)

    adapter = AlpacaAdapter(
        mode=TradingMode.PAPER,
        api_key="k",
        api_secret="s",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://paper-api.alpaca.markets"
        ),
    )
    adapter.bind_api_reporter(reporter)
    return adapter, seen


async def test_successful_read_is_counted_ok():
    adapter, seen = _adapter(lambda r: httpx.Response(200, json=ACCOUNT_JSON))
    await adapter.get_account()
    assert seen == [True]


async def test_failed_read_is_counted_bad():
    """Дуудалт бүрд НЭГ мөр — retry-ийн 3 оролдлого нэг л дуудалт."""
    adapter, seen = _adapter(lambda r: httpx.Response(500, json={}))
    with pytest.raises(BrokerUnavailable):
        await adapter.get_account()
    assert seen == [False]


def _order() -> ValidatedOrder:
    return ValidatedOrder(
        symbol="AAPL",
        side=OrderSide.BUY,
        qty=Decimal("1"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id="p3-test-1",
        limit_price=None,
        stop_price=None,
    )


async def test_submit_order_outage_is_counted_bad():
    adapter, seen = _adapter(lambda r: httpx.Response(500, json={"message": "no"}))
    with pytest.raises(BrokerUnavailable):
        await adapter.submit_order(_order())
    assert seen == [False]


async def test_submit_order_rejection_is_counted_ok():
    """N-3 — татгалзал нь broker АМЬД гэдгийн нотолгоо.

    Өмнө нь 4xx бүр `api_error` = `False` болж энэ метрикийг ахиулдаг байв:
    ганц wash-trade татгалзал «Alpaca унаж байна» гэсэн дүр зурагт нэмэгддэг
    байсан. Татгалзал нь `order_reject_rate`-ийн хэрэг.
    """
    from app.broker.models import BrokerRejected

    adapter, seen = _adapter(
        lambda r: httpx.Response(403, json={"code": 42210000, "message": "wash trade"})
    )
    with pytest.raises(BrokerRejected):
        await adapter.submit_order(_order())
    assert seen == [True]


async def test_empty_window_is_unmeasured_not_zero(db_session, settings, broker):
    """Хэмжигдээгүйг `0.0000` гэж харуулах нь худал ногоон (хавсралт 10)."""
    reading = next(
        r
        for r in await CircuitBreaker(db_session, settings=settings, broker=broker).measure()
        if r.metric == API_ERROR_RATE
    )
    assert reading.value == "unmeasured"
    assert reading.tripped is False


async def test_broker_outage_trips_api_error_rate_alone(db_session, settings, broker):
    """Alpaca бүрэн унасан: `daily_loss` хэмжигдэхгүй ч энэ метрик halt үүсгэнэ."""
    broker.reachable = False
    machine = StateMachine(db_session, wind_down_grace=settings.WIND_DOWN_GRACE)
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="тест")
    for _ in range(10):
        await breaker_mod.record(db_session, "api_error", ok=False)
    await db_session.commit()

    tripped = await CircuitBreaker(db_session, settings=settings, broker=broker).enforce()
    assert [r.metric for r in tripped] == [API_ERROR_RATE]
    assert (await machine.current()).state is SystemState.HALTED
