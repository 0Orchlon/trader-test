"""Детерминистик exit manager (T-99) — нээхээс гадна ХААХ зам."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from itertools import count

from app import models
from app.broker.models import OrderSide, SystemState, TimeInForce
from app.execution.exits import _hidden_zero_crossing, evaluate_exits, run_exits
from app.util.time import now_utc
from tests.fakes import position, quote

NOW = now_utc()
STOP = Decimal("2.5")
TAKE = Decimal("6.0")
HOLD = timedelta(hours=48)


def _evaluate(
    last: str,
    *,
    held: timedelta = timedelta(minutes=1),
    qty: str = "10",
    agent_qty: str | None = None,
    basis: str = "100.00",
):
    # `basis` нь АГЕНТЫН ӨӨРИЙН өртөг (позицийн дундаж БИШ) — 100.00 үед
    # хувь нь шууд уншигдана.
    pos = position("AAPL", qty, "1000.00")
    return evaluate_exits(
        [pos],
        {"AAPL": quote("AAPL", last)},
        {"AAPL": Decimal(agent_qty if agent_qty is not None else qty)},
        {"AAPL": Decimal(basis)},
        {"AAPL": NOW - held},
        NOW,
        stop_pct=STOP,
        take_pct=TAKE,
        max_hold=HOLD,
    )


def test_below_stop_fires():
    [intent] = _evaluate("97.00")
    assert (intent.reason, intent.side) == ("stop_loss", OrderSide.SELL)


def test_above_target_fires():
    [intent] = _evaluate("107.00")
    assert intent.reason == "take_profit"


def test_in_between_with_a_fresh_clock_does_not_fire():
    assert _evaluate("101.00") == []


def test_old_and_flat_fires_on_max_hold():
    [intent] = _evaluate("100.00", held=timedelta(hours=49))
    assert intent.reason == "max_hold"


def test_emitted_qty_never_exceeds_position_qty():
    for last in ("50.00", "100.00", "500.00"):
        for intent in _evaluate(last, held=timedelta(hours=72), qty="7"):
            assert intent.qty == Decimal("7")


def test_qty_is_clipped_to_what_the_agent_itself_bought():
    # Позиц 10 ширхэг ч агент өөрөө 2-ыг л авсан — үлдсэн 8 нь операторынх.
    [intent] = _evaluate("97.00", qty="10", agent_qty="2")
    assert intent.qty == Decimal("2")


def test_the_trigger_reads_our_own_basis_not_the_position_average():
    """Позицийн дундаж 100.00 ч манай өртөг 200.00 — 100.00 нь -50%, stop."""
    [intent] = _evaluate("100.00", qty="10", agent_qty="2", basis="200.00")
    assert (intent.reason, intent.qty) == ("stop_loss", Decimal("2"))
    # Урвуугаар: манай өртгөөр +2% нь ямар ч хаалт биш (позицийн дунджаар -49%).
    assert _evaluate("51.00", qty="10", agent_qty="2", basis="50.00") == []


def test_a_symbol_the_agent_does_not_own_is_never_closed():
    pos = position("AAPL", "10", "1000.00")
    assert evaluate_exits(
        [pos], {"AAPL": quote("AAPL", "50.00")}, {}, {"AAPL": Decimal("100.00")},
        {"AAPL": NOW - timedelta(minutes=1)}, NOW,
        stop_pct=STOP, take_pct=TAKE, max_hold=HOLD,
    ) == []


def test_unknown_price_is_not_permission_to_close():
    pos = position("AAPL", "10", "1000.00")
    assert evaluate_exits(
        [pos], {}, {"AAPL": Decimal("10")}, {"AAPL": Decimal("100.00")},
        {"AAPL": NOW - timedelta(days=9)}, NOW,
        stop_pct=STOP, take_pct=TAKE, max_hold=HOLD,
    ) == []


def test_unknown_own_basis_is_not_permission_to_close():
    """Өөрийн өртгөө мэдэхгүй бол хаахгүй — холимог дундажаар буудахгүй."""
    pos = position("AAPL", "10", "1000.00")
    assert evaluate_exits(
        [pos], {"AAPL": quote("AAPL", "50.00")}, {"AAPL": Decimal("2")}, {},
        {"AAPL": NOW - timedelta(days=9)}, NOW,
        stop_pct=STOP, take_pct=TAKE, max_hold=HOLD,
    ) == []


def test_unverifiable_basis_forces_a_conservative_stop_instead_of_silence():
    """Өртгийг ТООЦООД чадаагүй (`unverifiable_basis`) symbol нь «мэдэхгүй» шиг
    чимээгүй алгасагдахгүй — жинхэнэ stop-loss мөнхөд дарагдахаас сэргийлж
    ЗААВАЛ stop_loss-оор хаана (false-positive нь чимээгүй дарагдсан
    жинхэнэ stop-ээс хямд)."""
    pos = position("AAPL", "10", "1000.00")
    [intent] = evaluate_exits(
        [pos], {"AAPL": quote("AAPL", "101.00")}, {"AAPL": Decimal("10")}, {},
        {"AAPL": NOW - timedelta(minutes=1)}, NOW,
        stop_pct=STOP, take_pct=TAKE, max_hold=HOLD,
        unverifiable_basis=frozenset({"AAPL"}),
    )
    assert intent.reason == "stop_loss"


async def _seed(engine, settings, entries=(("BTC/USD", "research_agent", "2"),)):
    """ACTIVE төлөв + өгөгдсөн filled оролтууд.

    `entries` = (symbol, origin, qty[, origin_detail]).
    """
    from app.db import make_sessionmaker
    from app.system.state import StateMachine

    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        machine = StateMachine(session, wind_down_grace=settings.WIND_DOWN_GRACE)
        await machine.ensure_initialised()
        await machine.transition(SystemState.ACTIVE, by="operator", reason="тест")
        for index, entry in enumerate(entries):
            symbol, origin, qty = entry[:3]
            session.add(
                models.Order(
                    client_order_id=f"p3-entry-{symbol}-{index}",
                    symbol=symbol,
                    side="buy",
                    qty=Decimal(qty),
                    filled_qty=Decimal(qty),
                    order_type="market",
                    time_in_force="gtc",
                    status="filled",
                    origin=origin,
                    origin_detail=entry[3] if len(entry) > 3 else None,
                    risk_evaluation={"decision": "APPROVE"},
                    mode="paper",
                    submitted_at=NOW + timedelta(seconds=index),
                    filled_at=NOW + timedelta(seconds=index),
                )
            )
        await session.commit()
    return sessionmaker


_SEQ = count()


async def _add_row(
    sessionmaker,
    symbol: str,
    side: str,
    origin: str,
    qty: str,
    *,
    status: str = "filled",
    at: datetime = NOW,
    price: str | None = None,
    filled_qty: str | None = None,
):
    """Нэг захиалгын мөр (+ `price` өгвөл түүнд харгалзах бодит fill).

    `filled_qty` заавал биш: өгөхгүй бол `status`-аас (хуучин зан) таамаглана.
    Round 9 repro-д (хэсэгчлэн биелээд `canceled`/`expired`/`failed` болсон
    мөр) ИЛ утга дамжуулна — тэр тохиолдолд `status`-аас таамаглах БУРУУ."""
    index = next(_SEQ)
    async with sessionmaker() as session:
        filled = (
            Decimal(filled_qty)
            if filled_qty is not None
            else Decimal(qty) if status in ("filled", "partially_filled") else Decimal(0)
        )
        row = models.Order(
            client_order_id=f"p3-row-{index}",
            symbol=symbol,
            side=side,
            qty=Decimal(qty),
            filled_qty=filled,
            order_type="market",
            time_in_force="gtc",
            status=status,
            origin=origin,
            risk_evaluation={"decision": "APPROVE"},
            mode="paper",
            submitted_at=at,
            filled_at=at,
        )
        session.add(row)
        await session.flush()
        if price is not None:
            session.add(
                models.Fill(
                    order_id=row.id,
                    broker_fill_id=f"fill-{index}",
                    qty=filled,
                    price=Decimal(price),
                    filled_at=at,
                    raw={},
                )
            )
        await session.commit()


async def _add_exit_row(sessionmaker, *, status: str, filled_qty: str, qty: str = "2"):
    """Агентын хаалтын мөр — ЯГ ямар төлөвтэй үлдсэнийг тестүүд өгнө."""
    async with sessionmaker() as session:
        session.add(
            models.Order(
                client_order_id=f"exit-BTCUSD-{status}",
                symbol="BTC/USD",
                side="sell",
                qty=Decimal(qty),
                filled_qty=Decimal(filled_qty),
                order_type="market",
                time_in_force="gtc",
                status=status,
                origin="research_agent",
                origin_detail="exit:stop_loss",
                risk_evaluation={"reduce_only_exit": "stop_loss"},
                mode="paper",
                submitted_at=NOW + timedelta(seconds=30),
                filled_at=NOW + timedelta(seconds=30),
            )
        )
        await session.commit()


async def test_run_exits_closes_only_our_position(engine, settings, broker):
    """Attribution — operator/external позицийг ХЭЗЭЭ Ч хөндөхгүй."""
    sessionmaker = await _seed(
        engine,
        settings,
        (("BTC/USD", "research_agent", "2"), ("AAPL", "manual_operator", "2")),
    )
    broker.positions = [position("BTCUSD", "2", "180.00"), position("AAPL", "2", "180.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00"), "AAPL": quote("AAPL", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert [(o.symbol, o.side.value, str(o.qty)) for o in broker.submitted] == [
        ("BTC/USD", "sell", "2")
    ]
    assert broker.submitted[0].time_in_force is TimeInForce.GTC
    async with sessionmaker() as session:
        row = (
            await session.execute(
                models.Order.__table__.select().where(
                    models.Order.origin_detail == "exit:stop_loss"
                )
            )
        ).one()
        # `entry_price` нь submit-тэй хамт; `realized_pl`-ыг ЗӨВХӨН ingest
        # бодит fill дээр бичнэ — энэ мөр `accepted`, filled_qty 0.
        assert row.entry_price == Decimal("100.00")
        assert row.realized_pl is None


async def test_run_exits_never_sells_operator_shares(engine, settings, broker):
    """Агент 2-ыг авсан, оператор Alpaca UI-аас 8 нэмсэн → зөвхөн 2 зарна."""
    sessionmaker = await _seed(engine, settings, ())
    await _add_row(sessionmaker, "BTC/USD", "buy", "research_agent", "2", price="100.00")
    broker.positions = [position("BTCUSD", "10", "900.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert [o.qty for o in broker.submitted] == [Decimal("2")]
    async with sessionmaker() as session:
        row = (
            await session.execute(
                models.Order.__table__.select().where(
                    models.Order.origin_detail == "exit:stop_loss"
                )
            )
        ).one()
        # Хэсэгчлэн зарсан ч `entry_price` нь МАНАЙ ӨӨРИЙН биелэлтийн үнэ
        # (позицийн холимог дундаж БИШ) — realized_pl нь бодит мөнгө.
        assert row.entry_price == Decimal("100.00")


async def test_a_canceled_after_partial_exit_still_counts_against_our_holding(
    engine, settings, broker
):
    """Хэсэгчлэн биелээд `canceled` болсон зарах order нь ШИРХЭГ ХӨДӨЛГӨСӨН.

    Түүнийг цэвэр bielelt-ээс хаявал агент өөрийнхөө аль хэдийн зарсан 2-ыг
    дахин зарна — тэр нь операторын ширхэг.
    """
    sessionmaker = await _seed(engine, settings)
    await _add_exit_row(sessionmaker, status="canceled", filled_qty="2")
    broker.positions = [position("BTCUSD", "8", "720.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_a_failed_row_that_actually_executed_is_not_sold_twice(
    engine, settings, broker
):
    """`_fail` нь timeout дээр `failed`, filled_qty **0** бичдэг ч order Alpaca
    дээр биелсэн байж болно. Энэ нь ЭХЛЭЭД тулгалтын ажил: мөрийг зассан
    байдлаар нь суулгавал зөвхөн цэвэр bielelt-ийг шалгана, тулгалтыг БИШ.

    Тиймээс энд бодит дараалал явна: orphan мөр → `reconcile` → `run_exits`.
    """
    from dataclasses import replace

    from app.broker.models import OrderStatus
    from app.broker.reconcile import reconcile
    from tests.fakes import broker_order

    sessionmaker = await _seed(engine, settings)
    # ЯГ `_fail`-ийн бичдэг хэлбэр: `failed`, биелэлт 0.
    await _add_exit_row(sessionmaker, status="failed", filled_qty="0")
    # Alpaca дээр тэр order БИЕЛСЭН — `filled` нь терминал тул `status=open`
    # жагсаалтад ХЭЗЭЭ Ч харагдахгүй, зөвхөн нэрээр нь асуувал олдоно.
    broker.terminal_orders = [
        replace(
            broker_order("exit-BTCUSD-failed", symbol="BTC/USD"),
            status=OrderStatus.FILLED,
            qty=Decimal("2"),
            filled_qty=Decimal("2"),
            filled_at=NOW + timedelta(seconds=30),
        )
    ]
    async with sessionmaker() as session:
        report = await reconcile(session, broker, settings=settings)
    assert [d.kind for d in report.drifts] == ["status_mismatch"]

    broker.positions = [position("BTCUSD", "8", "720.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    # Оролт 2 − биелсэн хаалт 2 = 0 → агент энд юу ч эзэмшихгүй.
    assert broker.submitted == []


async def test_a_provider_fallback_does_not_disable_the_stop_loss(engine, settings, broker):
    """Хоёр оролт хоёулаа агентынх, зөвхөн model id нь өөр (provider fallback).

    `Attribution.mixed` нь (origin, detail) хосоор ялгадаг тул энэ нь «холимог»
    харагддаг байв — позиц үүрд хаагдахгүй үлдэнэ.
    """
    sessionmaker = await _seed(
        engine,
        settings,
        (
            ("BTC/USD", "research_agent", "5", "anthropic/claude-opus-5"),
            ("BTC/USD", "research_agent", "5", "local-fallback/qwen3:4b-instruct"),
        ),
    )
    broker.positions = [position("BTCUSD", "10", "900.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert [(o.symbol, o.side.value, str(o.qty)) for o in broker.submitted] == [
        ("BTC/USD", "sell", "10")
    ]


async def test_a_symbol_outside_the_watchlist_is_never_exited(engine, settings, broker):
    """`BTCUSD` → `BTC/USD` буулгаж чадахгүй бол огт илгээхгүй: буулгаагүй
    crypto нь DAY TIF-тэй явж, амьд ослыг давтана."""
    settings = settings.model_copy(update={"RESEARCH_SYMBOLS": "AAPL,MSFT"})
    sessionmaker = await _seed(engine, settings)
    broker.positions = [position("BTCUSD", "2", "180.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00"), "BTCUSD": quote("BTCUSD", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_the_kill_switch_stops_every_exit(engine, settings, broker):
    """HALTED = ЗОГСОХ. Тойрох тохиргоо БАЙХГҮЙ."""
    from app.system.state import StateMachine

    sessionmaker = await _seed(engine, settings)
    async with sessionmaker() as session:
        machine = StateMachine(session, wind_down_grace=settings.WIND_DOWN_GRACE)
        await machine.transition(SystemState.HALTED, by="operator", reason="тест")
    broker.positions = [position("BTCUSD", "2", "180.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []
    assert not hasattr(settings, "EXIT_WHEN_HALTED")


async def test_reconcile_adopts_broker_truth_for_a_failed_row(db_session, broker, settings):
    """`failed` мөр Alpaca дээр амьд байвал EOD тулгалт түүнийг ЗАСНА.

    Засахгүй бол exit manager-ийн цэвэр bielelt үүрд илүү тоо харуулна.
    """
    from dataclasses import replace

    from app.broker.models import OrderStatus
    from app.broker.reconcile import reconcile
    from tests.fakes import broker_order

    db_session.add(
        models.Order(
            client_order_id="exit-BTCUSD-orphan",
            symbol="BTC/USD",
            side="sell",
            qty=Decimal("2"),
            filled_qty=Decimal("0"),
            order_type="market",
            time_in_force="gtc",
            status="failed",
            failure_reason="TimeoutError",
            origin="research_agent",
            origin_detail="exit:stop_loss",
            risk_evaluation={"reduce_only_exit": "stop_loss"},
            mode="paper",
            submitted_at=NOW,
        )
    )
    await db_session.commit()
    broker.open_orders = [
        replace(
            broker_order("exit-BTCUSD-orphan", symbol="BTC/USD"),
            status=OrderStatus.PARTIALLY_FILLED,
            filled_qty=Decimal("2"),
        )
    ]

    report = await reconcile(db_session, broker, settings=settings)
    assert [d.kind for d in report.drifts] == ["status_mismatch"]
    row = (
        await db_session.execute(
            models.Order.__table__.select().where(
                models.Order.client_order_id == "exit-BTCUSD-orphan"
            )
        )
    ).one()
    assert (row.status, row.filled_qty) == ("partially_filled", Decimal("2"))


async def test_a_failed_row_absent_at_the_broker_is_not_a_drift(db_session, broker, settings):
    """Хүрээгүй submit нь өдөр бүр зөрүү тоолж breaker-ийг худлаар унагахгүй."""
    from app.broker.reconcile import reconcile

    db_session.add(
        models.Order(
            client_order_id="exit-BTCUSD-never-sent",
            symbol="BTC/USD",
            side="sell",
            qty=Decimal("2"),
            filled_qty=Decimal("0"),
            order_type="market",
            time_in_force="gtc",
            status="failed",
            failure_reason="halted_before_submit",
            origin="research_agent",
            origin_detail="exit:stop_loss",
            risk_evaluation={"reduce_only_exit": "stop_loss"},
            mode="paper",
            submitted_at=NOW,
        )
    )
    await db_session.commit()

    assert (await reconcile(db_session, broker, settings=settings)).count == 0


async def test_run_exits_skips_a_mixed_symbol(engine, settings, broker):
    """Хэний ширхэг нь мэдэгдэхгүй бол огт хөндөхгүй."""
    sessionmaker = await _seed(
        engine,
        settings,
        (("BTC/USD", "manual_operator", "5"), ("BTC/USD", "research_agent", "2")),
    )
    broker.positions = [position("BTCUSD", "7", "630.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_a_closed_operator_round_trip_does_not_disable_the_stop_loss(
    engine, settings, broker
):
    """Оператор аль эрт авч, зарсан (цэвэр 0) — ӨНӨӨДӨР түүнд нэг ч ширхэг алга.

    Эзэмшлийг ТҮҮХЭЭР шүүвэл тэр хаагдсан round-trip нь тухайн symbol-ын
    stop-loss-ыг ҮҮРД унтраадаг байв. Асуулт нь «ОДОО хэн эзэмшиж байна».
    """
    sessionmaker = await _seed(engine, settings, ())
    await _add_row(sessionmaker, "BTC/USD", "buy", "manual_operator", "3")
    await _add_row(sessionmaker, "BTC/USD", "sell", "manual_operator", "3")
    await _add_row(sessionmaker, "BTC/USD", "buy", "research_agent", "2", price="100.00")
    broker.positions = [position("BTCUSD", "2", "180.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert [(o.symbol, o.side.value, str(o.qty)) for o in broker.submitted] == [
        ("BTC/USD", "sell", "2")
    ]


async def test_the_trigger_ignores_the_operator_blended_cost_basis(engine, settings, broker):
    """Агент 200-аар авсан, операторын хямд лот дунджийг 100 болгосон.

    Позицийн дундажаар бодвол 100.00 нь «0%» — манай лот -50% байхад stop
    ажиллахгүй. Trigger нь МАНАЙ өртгөөс.
    """
    sessionmaker = await _seed(engine, settings, ())
    await _add_row(sessionmaker, "BTC/USD", "buy", "research_agent", "2", price="200.00")
    broker.positions = [position("BTCUSD", "10", "1000.00")]  # avg_entry_price=100.00
    broker.quotes = {"BTC/USD": quote("BTC/USD", "100.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert [(o.side.value, o.qty) for o in broker.submitted] == [("sell", Decimal("2"))]
    async with sessionmaker() as session:
        row = (
            await session.execute(
                models.Order.__table__.select().where(
                    models.Order.origin_detail == "exit:stop_loss"
                )
            )
        ).one()
        assert row.entry_price == Decimal("200.00")


async def test_the_blended_basis_does_not_fire_a_stop_we_do_not_have(
    engine, settings, broker
):
    """Урвуу тал: позицийн дундажаар -49% ч манай лот +2% — хаалт БАЙХГҮЙ."""
    sessionmaker = await _seed(engine, settings, ())
    await _add_row(sessionmaker, "BTC/USD", "buy", "research_agent", "2", price="50.00")
    broker.positions = [position("BTCUSD", "10", "510.00")]  # avg_entry_price=100.00
    broker.quotes = {"BTC/USD": quote("BTC/USD", "51.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_a_fillless_reconciled_tranche_does_not_suppress_a_real_stop(
    engine, settings, broker
):
    """Round 4-ийн reconcile засвар шинэ хаалгаар давтуулсан алдаа: нэг lot
    Fill-тэй (100.00), нөгөө lot нь reconcile-ээр `filled_qty` засагдсан ч
    Fill мөргүй хэлбэр (`BrokerOrder`-д fill-ийн дундаж үнэ огт байхгүй тул
    reconcile Fill мөр үүсгэж ЧАДАХГҮЙ). Хуучин код дутуу Fill-ийг чимээгүй
    жигнэсэн дундаж мэт хэрэглээд 100.00 гаргадаг байсан — 100.00 үнэ дээр
    энэ нь «0%», үхсэн бүс, stop идэхгүй. Гэтэл позиц БҮХЭЛДЭЭ манайх тул
    broker-ийн бодит дундаж (130.00) итгэмжтэй — 100.00 үнэ дээр -23% буюу
    ЖИНХЭНЭ stop_loss ёстой."""
    from app.broker.models import Position, PositionSide

    sessionmaker = await _seed(engine, settings, ())
    await _add_row(sessionmaker, "BTC/USD", "buy", "research_agent", "2", price="100.00")
    # Reconcile-ээр засагдсан хэлбэр: filled_qty бий, Fill мөр АЛГА.
    await _add_row(sessionmaker, "BTC/USD", "buy", "research_agent", "2", price=None)
    broker.positions = [
        Position(
            symbol="BTCUSD",
            qty=Decimal("4"),
            side=PositionSide.LONG,
            avg_entry_price=Decimal("130.00"),
            market_value=Decimal("400.00"),
            unrealized_pl=Decimal("0.00"),
        )
    ]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "100.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert [(o.symbol, o.side.value, str(o.qty)) for o in broker.submitted] == [
        ("BTC/USD", "sell", "4")
    ]
    async with sessionmaker() as session:
        row = (
            await session.execute(
                models.Order.__table__.select().where(
                    models.Order.origin_detail == "exit:stop_loss"
                )
            )
        ).one()
        # Позиц БҮХЭЛДЭЭ манайх тул broker-ийн дундаж нь ЯГ манай өртөг.
        assert row.entry_price == Decimal("130.00")


async def test_a_partially_tracked_position_with_no_safe_anchor_is_still_closed(
    engine, settings, broker
):
    """Дээрхтэй адил хоёр lot (Fill-тэй + Fill-гүй, нийт 4) ч broker дээрх
    ЕРӨНХИЙ позиц (6) манай мэдэгдэж буй нийлбэрээс их — 2 ширхэг ЯМАР Ч Order
    мөргүй, үнэхээр батлагдашгүй. Аль ч арга (Fill дундаж, БҮХЭЛ позиц)
    батлагдахгүй ч чимээгүй алгасахгүй: force stop_loss хаана, гэхдээ
    батлагдаагүй тоог `entry_price`/`realized_pl`-д хэзээ ч бичихгүй."""
    sessionmaker = await _seed(engine, settings, ())
    await _add_row(sessionmaker, "BTC/USD", "buy", "research_agent", "2", price="100.00")
    await _add_row(sessionmaker, "BTC/USD", "buy", "research_agent", "2", price=None)
    broker.positions = [position("BTCUSD", "6", "600.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert [(o.symbol, o.side.value, o.qty) for o in broker.submitted] == [
        ("BTC/USD", "sell", Decimal("4"))
    ]
    async with sessionmaker() as session:
        row = (
            await session.execute(
                models.Order.__table__.select().where(
                    models.Order.origin_detail == "exit:stop_loss"
                )
            )
        ).one()
        assert row.entry_price is None
        assert row.realized_pl is None


async def test_a_stranded_pending_risk_row_blocks_a_second_exit(engine, settings, broker):
    """`ExecutionAgent` нь submit-ЭЭС ӨМНӨ `pending_risk` мөр commit хийдэг.

    Тэр цонхонд процесс унавал мөр үүрд `pending_risk` үлдэнэ. Түүнийг
    «нээлттэй биш» гэж үзвэл дараагийн мөчлөг ижил ширхгийг ДАХИН зарна.
    """
    sessionmaker = await _seed(engine, settings)
    await _add_exit_row(sessionmaker, status="pending_risk", filled_qty="0")
    broker.positions = [position("BTCUSD", "2", "180.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_our_own_partial_exit_fill_does_not_push_the_max_hold_clock(
    engine, settings, broker
):
    """max_hold цаг нь ОРОЛТЫН цаг. Гаралтын биелэлтийг тоовол мөчлөг бүрт
    урагшилж, хугацаат хаалт хэзээ ч ажиллахгүй."""
    sessionmaker = await _seed(engine, settings, ())
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "4",
        at=NOW - timedelta(hours=60), price="100.00",
    )
    await _add_row(sessionmaker, "BTC/USD", "sell", "research_agent", "1", price="100.00")
    broker.positions = [position("BTCUSD", "3", "300.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "100.00")}  # stop ч, target ч биш
    await run_exits(sessionmaker, settings, broker, None)

    assert [(o.side.value, o.qty) for o in broker.submitted] == [("sell", Decimal("3"))]
    async with sessionmaker() as session:
        row = (
            await session.execute(
                models.Order.__table__.select().where(
                    models.Order.origin_detail == "exit:max_hold"
                )
            )
        ).one()
        assert row.entry_price == Decimal("100.00")


async def test_a_clean_partial_exit_with_untracked_extra_units_is_verified(
    engine, settings, broker
):
    """round 5-ийн GROSS алдаа: Fill-ийн бүрхэлтийг зөвхөн buy талын нийлбэрээр
    (`acc[0]`, хэзээ ч sell-ээр цэвэрлэгддэггүй) `agent_qty`-тай (цэвэр,
    buy-sell) харьцуулж байсан тул хэсэгчилсэн ГАРАЛТтай ХАМГИЙН ЭНГИЙН, бүрэн
    Fill-тэй symbol ч «дутуу» гэж буруу тооцогдоно. Broker дээрх позиц манайхаас
    их (гадны 1 ширхэг, ямар ч Order мөргүй) тул «БҮХЭЛДЭЭ манайх» fallback ч
    тохирохгүй → force stop_loss хаачихдаг байв, ямар ч жинхэнэ trigger
    байхгүй атал.

    Агент 4 авч (Fill @100), 1-ийг зарсан (Fill @100) — хоёулаа БҮРЭН, цэвэр 3.
    Broker позиц 4 (1 нь гадны). Үнэ хөдлөөгүй (100.00) → ямар ч order
    илгээгдэх ёсгүй."""
    sessionmaker = await _seed(engine, settings, ())
    await _add_row(sessionmaker, "BTC/USD", "buy", "research_agent", "4", price="100.00")
    await _add_row(sessionmaker, "BTC/USD", "sell", "research_agent", "1", price="100.00")
    broker.positions = [position("BTCUSD", "4", "400.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "100.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_a_closed_and_reopened_lot_uses_only_the_current_lots_basis(
    engine, settings, broker
):
    """ROUND 7 repro: 2ш @100 авч, 2ш @100 зараад (цэвэр 0, ХААГДСАН), дараа нь
    3ш @50 ДАХИН авсан (ЯГ ОДООГИЙН лот). Хуучин лотыг холбовол
    (2*100+3*50)/5=70.00 гэсэн БОХИР дундаж гарч, 52.00 үнэ дээр -25.7%
    (жинхэнэ +4% байхад) хуурамч stop_loss буудна. Лот-scoping зөв бол
    өртөг ЯГ 50.00, 52.00 нь ±2.5%/6.0% зурвасын дотор — ямар ч хаалт үгүй."""
    sessionmaker = await _seed(engine, settings, ())
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "2",
        at=NOW - timedelta(minutes=10), price="100.00",
    )
    await _add_row(
        sessionmaker, "BTC/USD", "sell", "research_agent", "2",
        at=NOW - timedelta(minutes=9), price="100.00",
    )
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "3",
        at=NOW, price="50.00",
    )
    broker.positions = [position("BTCUSD", "3", "150.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "52.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_a_partially_filled_then_canceled_close_still_crosses_the_lot_boundary(
    engine, settings, broker
):
    """ROUND 9 repro: хуучин лотыг ХААХ гараа (sell) ХЭСЭГЧЛЭН биелээд (Fill
    бодитоор бий) эцэст нь `canceled` болсон (жишээ нь DAY order зах хаагдахад
    цуцлагдсан, эсвэл `cancel_all_orders`-ээр wind-down дунд цуцлагдсан).

    `lot_events` хуучин `row.status not in FILLED_STATUSES` шүүлтээр энэ мөрийг
    ЯЛГААГҮЙ орхидог байсан (filled_qty>0 ч status нь FILLED/PARTIALLY_FILLED
    БИШ тул) — zero-crossing огт бүртгэгдэхгүй, `lot_start` тогтоогдохгүй, тул
    ДАРАА нь ирсэн шинэ лот (3ш @50) хуучин лотын Fill-тэй (2ш @100) буруугаар
    пулдаж (2*100+3*50)/5=70.00 гэсэн БОХИР дундаж гаргадаг байсан. 52.00 үнэ
    дээр энэ нь -25.7% (жинхэнэ +4% байхад) ХУУРАМЧ stop_loss буудна.

    filled_qty-гаар (статусаас үл хамааран) зөв шүүвэл лот ЗӨВ хаагдаж, шинэ
    лотын ЖИНХЭНЭ өртөг (50.00) хэрэглэгдэнэ — 52.00 нь +4%, ямар ч хаалт
    гарахгүй (round 7/8-ийн test-үүдтэй яг адил хэлбэр)."""
    sessionmaker = await _seed(engine, settings, ())
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "2",
        at=NOW - timedelta(minutes=10), price="100.00",
    )
    # Хуучин лотыг ХААХ гараа: захиалга 3ш, ХЭСЭГЧЛЭН (2ш) биелээд `canceled`.
    await _add_row(
        sessionmaker, "BTC/USD", "sell", "research_agent", "3",
        status="canceled", filled_qty="2",
        at=NOW - timedelta(minutes=9), price="100.00",
    )
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "3",
        at=NOW, price="50.00",
    )
    broker.positions = [position("BTCUSD", "3", "150.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "52.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


def test_hidden_zero_crossing_finds_a_boundary_reachable_by_some_order():
    """Хуучин лот 2 ширхэгтэй (`net_before`), бүлэгт хаах -2 БОЛОН нээх +3
    хамт орсон бол {-2} дэд олонлог ГАНЦААРАА -2-той тэнцэх тул ЗАРИМ дотоод
    дараалал дор running яг 0 дайрна — ambiguous ёстой."""
    assert _hidden_zero_crossing(Decimal("2"), [Decimal("-2"), Decimal("3")]) is True


def test_hidden_zero_crossing_is_false_when_no_subset_can_reach_zero():
    """Хоёул НЭГ тал (buy) — running зөвхөн ӨСНӨ, 0-ыг хэзээ ч дайрахгүй тул
    ямар ч дэд олонлог `-net_before`-тэй тэнцэхгүй (false-positive шалгалт)."""
    assert _hidden_zero_crossing(Decimal("5"), [Decimal("2"), Decimal("1")]) is False


async def test_a_same_timestamp_close_and_reopen_falls_back_to_the_safe_path(
    engine, settings, broker
):
    """ROUND 8 repro: round 7-ийн бүлэглэлт зөвхөн бүлгийн ТӨГСГӨЛийн НИЙТ
    дельта 0 мөн эсэхийг шалгадаг байсан. Хуучин лот ХААХ (sell 2) БОЛОН шинэ
    лот НЭЭХ (buy 3) хоёул ЯГ НЭГ `filled_at`-тай бол бүлгийн нийт дельта +1
    (0 БИШ) тул 0 хэзээ ч бүртгэгдэхгүй, хуучин лотын Fill (@100) шинэ лотод
    (@50) чимээгүй холилдож (2*100+3*50)/5=70.00 БОХИР дундаж гаргадаг байсан
    — 52.00 үнэ дээр -25.7% (жинхэнэ +4% байхад) ХУУРАМЧ stop_loss буудаг байв.

    Round 8: энэ tie-г ТОДОРХОЙГҮЙ гэж танина (жинхэнэ round 7 репро) — Fill-
    ээр батлагдах оролдлого хийхгүй, харин позиц БҮХЭЛДЭЭ манайх тул broker-ийн
    бодит дундаж (50.00, яг шинэ лотын жинхэнэ өртөг) руу унана. 52.00 дээр
    энэ нь +4% — ямар ч хаалт ЗӨВӨӨР гарахгүй."""
    from app.broker.models import Position, PositionSide

    sessionmaker = await _seed(engine, settings, ())
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "2",
        at=NOW - timedelta(minutes=10), price="100.00",
    )
    await _add_row(
        sessionmaker, "BTC/USD", "sell", "research_agent", "2",
        at=NOW, price="100.00",
    )
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "3",
        at=NOW, price="50.00",
    )
    broker.positions = [
        Position(
            symbol="BTCUSD",
            qty=Decimal("3"),
            side=PositionSide.LONG,
            avg_entry_price=Decimal("50.00"),
            market_value=Decimal("156.00"),
            unrealized_pl=Decimal("0.00"),
        )
    ]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "52.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_a_tied_same_side_group_inside_a_continuing_lot_is_not_ambiguous(
    engine, settings, broker
):
    """False-positive шалгалт: тэнцүү цагтай ч ХОЁУЛАА buy (нэг тал) бүлэг —
    лот хэзээ ч хаагдаагүй (running зөвхөн ӨСНӨ, 0-ыг дайрах аргагүй) тул
    ambiguous БОЛОХГҮЙ ёстой — Fill-ээр бодсон ЖИНХЭНЭ дундаж (135.00) хэвээр
    хэрэглэгдэж, жинхэнэ stop_loss гарна. Хэт консерватив байдал (энгийн
    tie-г ч ТОДОРХОЙГҮЙ гэж үзэх) энд шалгагдана."""
    sessionmaker = await _seed(engine, settings, ())
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "3",
        at=NOW - timedelta(minutes=10), price="100.00",
    )
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "2",
        at=NOW, price="100.00",
    )
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "5",
        at=NOW, price="170.00",
    )
    broker.positions = [position("BTCUSD", "10", "1000.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "131.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert [(o.side.value, o.qty) for o in broker.submitted] == [("sell", Decimal("10"))]
    async with sessionmaker() as session:
        row = (
            await session.execute(
                models.Order.__table__.select().where(
                    models.Order.origin_detail == "exit:stop_loss"
                )
            )
        ).one()
        # Fill-ээр бодсон ЖИНХЭНЭ дундаж (3*100+2*100+5*170)/10 = 135.00 —
        # ambiguous fallback (broker дундаж 100.00, `position()`-ийн
        # тогтмол утга) РУУ БУРУУГААР ороогүйг батална.
        assert row.entry_price == Decimal("135.00")


async def test_a_fillless_tranche_inside_a_reopened_lot_is_still_unverifiable(
    engine, settings, broker
):
    """Хоёр алдаа НЭГ дээр: хуучин лот бүрэн хаагдсан (2 ш @100 Fill-тэй авч,
    3 ш зарсан ч Fill-ГҮЙ — reconcile-ээр засагдсан), дараа нь ШИНЭ лот
    нээгдсэн ч тэр ч мөн Fill-гүй хэсэгтэй (2 ш @50 Fill-тэй, 3 ш нэмж
    Fill-ГҮЙ). Broker дээр 7 ш (үүнээс 2 нь бүрмөсөн гадны, ямар ч Order
    мөргүй).

    Лот-scoping-гүй код хуучин лотын Fill (@100, 3ш) болон шинэ лотын Fill
    (@50, 2ш)-ийг ХАМТ пулдаж [5, 400] → дундаж 80.00 гаргадаг ба ЯГ ЭНЭ
    тохиолдолд Fill-ЭЭР бүрхэгдсэн цэвэр нийлбэр (5) `agent_qty`-тай (5)
    ТААРЧ — код үүнийг «БҮРЭН БАТЛАГДСАН» гэж БУРУУГААР дүгнэдэг байсан
    (жинхэнэ лот бол 3ш Fill-гүй тул үнэхээр ДУТУУ). 80.00 үнэ дээр 52.00-той
    харьцуулбал 0% — ямар ч хаалт гарахгүй. Зөв (лот-scoped) код шинэ лотыг
    ЗӨВХӨН харна: Fill бүрхэлт (2) ≠ ОДООГИЙН лотын жинхэнэ хэмжээ (5) →
    дутуу, мөн 7ш-ийн 2 нь ямар ч Order мөргүй тул broker дундаж ч итгэмжгүй →
    `unverifiable` → 80.00 үнээс ҮЛ ХАМААРАН ЗААВАЛ stop_loss хаана."""
    sessionmaker = await _seed(engine, settings, ())
    # Хуучин лот: 3ш @100 (Fill-тэй) авч, 3ш зарсан (Fill-ГҮЙ, reconcile) → 0.
    # Тоо санамсаргүй биш: хуучин лотын Fill-ээр бүрхэгдсэн (+3) ба жинхэнэ (0)
    # ялгаа нь шинэ лотын дутуу 3ш-тэй яг ТЭНЦҮҮ хэмжээгээр НӨХӨГДӨЖ, лот-
    # scoping-гүй код глобаль түвшинд «бүрэн» гэж БУРУУГААР дүгнэдэг байсныг
    # илчилнэ (доор тайлбарласан).
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "3",
        at=NOW - timedelta(minutes=10), price="100.00",
    )
    await _add_row(
        sessionmaker, "BTC/USD", "sell", "research_agent", "3",
        at=NOW - timedelta(minutes=9), price=None,
    )
    # Шинэ (одоогийн) лот: 2ш @50 (Fill-тэй) + 3ш (Fill-ГҮЙ, reconcile).
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "2",
        at=NOW, price="50.00",
    )
    await _add_row(
        sessionmaker, "BTC/USD", "buy", "research_agent", "3",
        at=NOW + timedelta(seconds=1), price=None,
    )
    broker.positions = [position("BTCUSD", "7", "700.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "80.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert [(o.symbol, o.side.value, o.qty) for o in broker.submitted] == [
        ("BTC/USD", "sell", Decimal("5"))
    ]
    async with sessionmaker() as session:
        row = (
            await session.execute(
                models.Order.__table__.select().where(
                    models.Order.origin_detail == "exit:stop_loss"
                )
            )
        ).one()
        assert row.entry_price is None
        assert row.realized_pl is None


async def test_a_late_terminal_transition_does_not_reorder_the_lot_boundary(
    engine, settings, broker
):
    """ROUND 10 repro: `ingest.TradeUpdateIngestor.apply` `Order.filled_at`-ыг
    ЗӨВХӨН терминал (`filled`/`canceled`/`expired`) статус хүрэхэд бичдэг —
    ХЭСЭГЧЛЭН биелэх БОДИТ мөчид БИШ. Хуучин лотыг ХААХ (sell) захиалга ЭРТ
    (T-15) хэсэгчлэн биелж (Fill мөр БОДИТ, эрт цагтай) гэвч зах хаагдсны
    дараа `canceled` болж, `Order.filled_at` нь ХОЖИМДСОН (T0) бичигдсэн.
    Яг тэр хоёр цагийн ДУНД (T-10) шинэ лотын оролт бүрэн биелчихсэн.

    `Order.filled_at`-аар эрэмблэсэн хуучин код [buy A(T-20), buy B(T-10),
    close A(T0)] гэсэн БУРУУ дараалал гаргаж (жинхэнэ дараалал: buy A, close
    A, buy B) zero-crossing-ыг ХЭЗЭЭ Ч олохгүй — шинэ лотын Fill (@50) хуучин
    лотын Fill-тэй (@100) чимээгүй холилдож (2*100+3*50)/5=70.00 БОХИР дундаж
    гаргадаг байсан. 52.00 үнэ дээр энэ нь -25.7% (жинхэнэ +4% байхад)
    ХУУРАМЧ stop_loss буудна. `Fill.filled_at` (бодит, ХОЦРОГДООГҮЙ цаг)
    хэрэглэвэл лот ЗӨВ хаагдаж, шинэ лотын цэвэр өртөг (50.00) ГАНЦААРАА
    хэрэглэгдэнэ — 52.00 нь +4%, ямар ч хаалт гарахгүй."""
    sessionmaker = await _seed(engine, settings, ())
    async with sessionmaker() as session:
        # Хуучин лот: 2ш @100, эрт бөгөөд шууд ТЕРМИНАЛ (filled_at=submitted).
        old_entry = models.Order(
            client_order_id="p10-old-entry",
            symbol="BTC/USD", side="buy", qty=Decimal("2"), filled_qty=Decimal("2"),
            order_type="market", time_in_force="gtc", status="filled",
            origin="research_agent", risk_evaluation={"decision": "APPROVE"},
            mode="paper",
            submitted_at=NOW - timedelta(minutes=20),
            filled_at=NOW - timedelta(minutes=20),
        )
        session.add(old_entry)
        await session.flush()
        session.add(models.Fill(
            order_id=old_entry.id, broker_fill_id="p10-old-entry-fill",
            qty=Decimal("2"), price=Decimal("100.00"),
            filled_at=NOW - timedelta(minutes=20), raw={},
        ))

        # Хуучин лотыг ХААХ (sell): ЭРТ (T-15) хэсэгчлэн биелсэн — Fill мөр
        # БОДИТ, эрт цагтай. Гэтэл зах хаагдсны дараа `canceled` болж,
        # `Order.filled_at` нь ХОЖИМ (T0, `ingest.apply`-ийн ЯГ адил зан) —
        # тэр бол терминал ШИЛЖИЛТИЙН цаг, бодит fill-ийн цаг БИШ.
        close_order = models.Order(
            client_order_id="p10-close",
            symbol="BTC/USD", side="sell", qty=Decimal("2"), filled_qty=Decimal("2"),
            order_type="market", time_in_force="gtc", status="canceled",
            origin="research_agent", origin_detail="exit:stop_loss",
            risk_evaluation={"reduce_only_exit": "stop_loss"}, mode="paper",
            submitted_at=NOW - timedelta(minutes=15),
            filled_at=NOW,
        )
        session.add(close_order)
        await session.flush()
        session.add(models.Fill(
            order_id=close_order.id, broker_fill_id="p10-close-fill",
            qty=Decimal("2"), price=Decimal("100.00"),
            filled_at=NOW - timedelta(minutes=15), raw={},
        ))

        # Шинэ лот: 3ш @50, хуучин ХААЛТЫН БОДИТ цаг (T-15) БОЛОН түүний
        # ХОЖИМДСОН terminal цаг (T0) хоёрын ДУНД (T-10) бүрэн биелсэн.
        new_entry = models.Order(
            client_order_id="p10-new-entry",
            symbol="BTC/USD", side="buy", qty=Decimal("3"), filled_qty=Decimal("3"),
            order_type="market", time_in_force="gtc", status="filled",
            origin="research_agent", risk_evaluation={"decision": "APPROVE"},
            mode="paper",
            submitted_at=NOW - timedelta(minutes=10),
            filled_at=NOW - timedelta(minutes=10),
        )
        session.add(new_entry)
        await session.flush()
        session.add(models.Fill(
            order_id=new_entry.id, broker_fill_id="p10-new-entry-fill",
            qty=Decimal("3"), price=Decimal("50.00"),
            filled_at=NOW - timedelta(minutes=10), raw={},
        ))
        await session.commit()

    broker.positions = [position("BTCUSD", "3", "150.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "52.00")}
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_max_hold_clock_uses_the_real_fill_not_a_late_terminal_stamp(
    engine, settings, broker
):
    """ROUND 10 audit follow-up: дээрх лотын хилийн ЯГ АДИЛ алдаа `entry_times`
    (max_hold) тооцоололд ХЭВЭЭР байсан. Оролтын захиалга ЭРТ (60ц өмнө)
    бүрэн биелсэн ч (Fill мөр бодит, эрт цагтай) DAY TIF учир зах хаагдахад
    (жишээ нь хэсэгчлэн биелсэн хэсгээс бусад нь) `canceled` болж,
    `Order.filled_at` нь ХОЖИМ (1 мин өмнө) бичигджээ. Хуучин код
    `Order.filled_at`-аар «сүүлийн оролт» тогтоовол позиц ОДОО Л нээгдсэн мэт
    харагдаж, 48ц max_hold хэзээ ч ажиллахгүй — ХАМГИЙН аюултай хэлбэр:
    хугацаат эрсдэлийн хаалт чимээгүй унтардаг. `Fill.filled_at`-аар (60ц
    өмнө) тооцвол max_hold ЗӨВ ажиллана."""
    sessionmaker = await _seed(engine, settings, ())
    async with sessionmaker() as session:
        real_fill_time = NOW - timedelta(hours=60)  # 48ц max_hold-оос хол
        row = models.Order(
            client_order_id="p10b-entry",
            symbol="BTC/USD", side="buy", qty=Decimal("3"), filled_qty=Decimal("3"),
            order_type="market", time_in_force="day", status="canceled",
            origin="research_agent", risk_evaluation={"decision": "APPROVE"},
            mode="paper",
            submitted_at=real_fill_time,
            filled_at=NOW - timedelta(minutes=1),  # терминал шилжилтийн цаг, БОДИТ fill биш
        )
        session.add(row)
        await session.flush()
        session.add(models.Fill(
            order_id=row.id, broker_fill_id="p10b-entry-fill",
            qty=Decimal("3"), price=Decimal("100.00"),
            filled_at=real_fill_time, raw={},
        ))
        await session.commit()

    broker.positions = [position("BTCUSD", "3", "300.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "100.00")}  # stop ч, target ч биш
    await run_exits(sessionmaker, settings, broker, None)

    assert [(o.side.value, o.qty) for o in broker.submitted] == [("sell", Decimal("3"))]
    async with sessionmaker() as session:
        closed = (
            await session.execute(
                models.Order.__table__.select().where(
                    models.Order.origin_detail == "exit:max_hold"
                )
            )
        ).one()
        assert closed is not None


async def test_run_exits_refuses_a_stale_quote(engine, settings, broker):
    sessionmaker = await _seed(engine, settings)
    broker.positions = [position("BTCUSD", "2", "180.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    broker.stale = True
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []


async def test_run_exits_blocks_on_a_broker_side_open_order(engine, settings, broker):
    """Timeout-д орсон exit / UI-аас тавьсан order зөвхөн broker талд харагдана."""
    from tests.fakes import broker_order

    sessionmaker = await _seed(engine, settings)
    broker.positions = [position("BTCUSD", "2", "180.00")]
    broker.quotes = {"BTC/USD": quote("BTC/USD", "90.00")}
    broker.open_orders = [broker_order("exit-BTCUSD-0", symbol="BTC/USD")]
    await run_exits(sessionmaker, settings, broker, None)

    assert broker.submitted == []
