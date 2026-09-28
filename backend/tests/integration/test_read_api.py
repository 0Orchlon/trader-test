"""T-07 (ID=634) — унших REST endpoint + `source` + холимог хориг.

DoD: (а) `source`-гүй хариу үүсгэх оролдлого алдаа; (б) enum-аас гадуур утга
татгалзана; (в) холимог `source` нийлүүлэх оролдлого УНАНА; (г) мөнгөн талбарт
float буцаах оролдлогыг барина.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.api.envelope import MixedSourceError, envelope, single_source
from app.broker.models import Source, SystemState
from tests.fakes import position


def test_envelope_requires_source():
    with pytest.raises(TypeError):
        envelope({"positions": []})  # type: ignore[call-arg]


def test_envelope_rejects_unknown_source():
    with pytest.raises(ValueError):
        envelope(
            {"positions": []},
            source="alpaca_demo",  # type: ignore[arg-type]
            system_state=SystemState.ACTIVE,
        )


def test_envelope_rejects_float_money():
    with pytest.raises(TypeError):
        envelope(
            {"equity": 104238.17},
            source=Source.ALPACA_PAPER,
            system_state=SystemState.ACTIVE,
        )


def test_single_source_rejects_mixture():
    with pytest.raises(MixedSourceError):
        single_source([Source.ALPACA_PAPER, Source.BACKTEST])


def test_single_source_accepts_uniform():
    assert single_source([Source.ALPACA_PAPER, Source.ALPACA_PAPER]) is Source.ALPACA_PAPER


def test_envelope_timestamps_are_utc_z():
    body = envelope({}, source=Source.ALPACA_PAPER, system_state=SystemState.ACTIVE)
    assert body["as_of"].endswith("Z")
    assert body["stale"] is False


async def test_get_account_passes_alpaca_values_through(client, broker):
    response = await client.get("/api/v1/account")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "alpaca_paper"
    assert body["account"]["equity"] == "104238.17"
    assert body["system_state"] == "halted"  # шинэ DB — initial_deploy


async def test_get_positions_carries_origin(client, broker, db_session):
    broker.positions = [position("AAPL", "40", "9012.00")]
    response = await client.get("/api/v1/positions")
    body = response.json()
    assert body["positions"][0]["origin"] == "external"
    assert body["positions"][0]["origin_detail"] is None


async def test_get_orders_filters_by_origin(client, seeded_orders):
    response = await client.get("/api/v1/orders", params={"status": "all", "origin": "manual_operator"})
    body = response.json()
    assert {o["origin"] for o in body["orders"]} == {"manual_operator"}


async def test_get_orders_money_fields_are_strings(client, seeded_orders):
    body = (await client.get("/api/v1/orders", params={"status": "all"})).json()
    for order in body["orders"]:
        assert isinstance(order["qty"], str)
        if order.get("limit_price") is not None:
            assert isinstance(order["limit_price"], str)


async def test_broker_unavailable_returns_503_problem(client, broker):
    broker.reachable = False
    response = await client.get("/api/v1/account")
    assert response.status_code == 503
    assert response.json()["code"] == "broker_unavailable"


async def test_health_reports_dependencies(client):
    body = (await client.get("/api/v1/health")).json()
    assert body["broker"]["name"] == "alpaca_paper"
    assert body["status"] in ("ok", "degraded", "down")
    assert body["source"] == "alpaca_paper"


async def test_backtest_rows_never_join_live_list(client, db_session):
    """AC-20/AC-21 — `source` холих оролдлого хариу угсрах үед УНАНА."""
    from app.api.envelope import single_source

    with pytest.raises(MixedSourceError):
        single_source([Source.ALPACA_PAPER, Source.ALPACA_LIVE])


def test_money_serialiser_rejects_float():
    from app.api.envelope import money_field

    with pytest.raises(TypeError):
        money_field(1.5)
    assert money_field(Decimal("1.5")) == "1.50"


# --- B-1: холимог origin далдлагдахгүй (LLD §16.4, §11.1) ---


async def _mixed_fill(db_session, symbol: str = "AAPL"):
    """Нэг symbol дээр ХОЁР origin-ийн fill — AI 10 ш, дараа нь operator 5 ш."""
    from datetime import timedelta

    from app import models
    from app.util.time import now_utc

    base = now_utc()
    db_session.add_all(
        [
            models.Order(
                client_order_id="p3-mix-agent",
                broker_order_id="brk-mix-agent",
                symbol=symbol,
                side="buy",
                qty=Decimal("10"),
                filled_qty=Decimal("10"),
                order_type="market",
                time_in_force="day",
                status="filled",
                origin="research_agent",
                origin_detail="claude-mcp/claude-opus-5",
                risk_evaluation={"decision": "APPROVE"},
                mode="paper",
                submitted_at=base,
                filled_at=base,
            ),
            models.Order(
                client_order_id="p3-mix-manual",
                broker_order_id="brk-mix-manual",
                symbol=symbol,
                side="buy",
                qty=Decimal("5"),
                filled_qty=Decimal("5"),
                order_type="market",
                time_in_force="day",
                status="filled",
                origin="manual_operator",
                origin_detail="operator",
                risk_evaluation={"decision": "APPROVE"},
                mode="paper",
                submitted_at=base + timedelta(minutes=1),
                filled_at=base + timedelta(minutes=1),
            ),
        ]
    )
    await db_session.commit()


async def test_mixed_symbol_appears_in_every_origin_group(client, broker, db_session):
    """§16.4 — холимог symbol нь БҮХ холбогдох картад харагдана, далдлахгүй."""
    await _mixed_fill(db_session)
    broker.positions = [position("AAPL", "15", "3330.00")]

    body = (await client.get("/api/v1/attribution")).json()
    origins = {
        group["origin"]
        for group in body["groups"]
        if any(row["symbol"] == "AAPL" for row in group["symbols"])
    }
    assert origins == {"research_agent", "manual_operator"}
    for group in body["groups"]:
        for row in group["symbols"]:
            if row["symbol"] == "AAPL":
                assert row["origin_mixed"] is True


async def test_single_origin_symbol_is_not_flagged_mixed(client, broker, seeded_orders):
    broker.positions = [position("AAPL", "10", "2215.00")]
    body = (await client.get("/api/v1/attribution")).json()
    rows = [row for group in body["groups"] for row in group["symbols"]]
    assert rows, "attribution хоосон байх ёсгүй"
    assert all(row["origin_mixed"] is False for row in rows)


async def test_a_symbol_whose_local_orders_net_flat_is_external(client, broker, db_session):
    """Хаагдсан локал арилжаа ирээдүйн позицийг эзэмшихгүй (LLD D-1)."""
    from datetime import timedelta

    from app import models
    from app.util.time import now_utc

    base = now_utc()
    db_session.add_all(
        [
            models.Order(
                client_order_id=f"p3-flat-{side}",
                broker_order_id=f"brk-flat-{side}",
                symbol="BTC/USD",
                side=side,
                qty=Decimal("1"),
                filled_qty=Decimal("1"),
                order_type="market",
                time_in_force="gtc",
                status="filled",
                origin="research_agent",
                origin_detail="local-ollama/qwen3:4b-instruct",
                risk_evaluation={"decision": "APPROVE"},
                mode="paper",
                submitted_at=base + timedelta(minutes=minute),
                filled_at=base + timedelta(minutes=minute),
            )
            for minute, side in enumerate(("buy", "sell"))
        ]
    )
    await db_session.commit()
    broker.positions = [position("BTCUSD", "0.5", "30000.00")]

    body = (await client.get("/api/v1/positions")).json()
    assert body["positions"][0]["origin"] == "external"


async def test_positions_flag_mixed_origin(client, broker, db_session):
    await _mixed_fill(db_session)
    broker.positions = [position("AAPL", "15", "3330.00")]
    body = (await client.get("/api/v1/positions")).json()
    assert body["positions"][0]["origin_mixed"] is True


# --- B-2: илгээхээс өмнөх notional-ийн quote эх сурвалж (LLD §16.5) ---


async def test_get_quote_returns_last_price_with_envelope(client, broker):
    from tests.fakes import quote

    broker.quotes = {"AAPL": quote("AAPL", "221.50")}
    response = await client.get("/api/v1/market/quote/AAPL")
    assert response.status_code == 200
    body = response.json()
    assert body["quote"]["last"] == "221.50"
    assert body["quote"]["symbol"] == "AAPL"
    assert body["source"] == "alpaca_paper"
    assert body["stale"] is False


async def test_get_quote_marks_stale_instead_of_hiding_it(client, broker):
    from tests.fakes import quote

    broker.quotes = {"AAPL": quote("AAPL", "221.50")}
    broker.stale = True
    body = (await client.get("/api/v1/market/quote/AAPL")).json()
    assert body["stale"] is True


async def test_get_quote_unknown_symbol_is_a_problem_not_a_guess(client, broker):
    response = await client.get("/api/v1/market/quote/NOPE")
    assert response.status_code == 503
    assert response.json()["code"] == "broker_unavailable"


# --- T-99: дэлгэцийн P&L нь модельд үзүүлсэн ЯГ ТЭР тоо ---


async def _closed_pair(db_session):
    """Хоёр хаагдсан order: +17.50 ба -12.50 → цэвэр +5.00."""
    from datetime import timedelta

    from app import models
    from app.util.time import now_utc

    base = now_utc()
    db_session.add_all(
        [
            models.Order(
                client_order_id=f"p3-closed-{i}",
                broker_order_id=f"brk-closed-{i}",
                symbol="AAPL",
                side="sell",
                qty=Decimal("2"),
                filled_qty=Decimal("2"),
                order_type="market",
                time_in_force="day",
                status="filled",
                origin="research_agent",
                origin_detail=detail,
                risk_evaluation={"decision": "APPROVE"},
                mode="paper",
                submitted_at=base + timedelta(minutes=i),
                filled_at=base + timedelta(minutes=i),
                realized_pl=pl,
            )
            for i, (pl, detail) in enumerate(
                ((Decimal("17.50"), "exit:take_profit"), (Decimal("-12.50"), "exit:stop_loss"))
            )
        ]
    )
    await db_session.commit()


async def test_performance_reports_the_same_net_the_prompt_was_shown(client, db_session):
    from app.agents.runner import closed_trade_stats

    await _closed_pair(db_session)
    stats = await closed_trade_stats(db_session)
    expected = sum(s["net"] for s in stats["per_symbol"])

    body = (await client.get("/api/v1/performance")).json()
    assert body["net"] == f"{expected:.2f}" == "5.00"
    assert body["per_symbol"] == [
        {"symbol": "AAPL", "trades": 2, "wins": 1, "losses": 1, "net": "5.00"}
    ]
    assert [r["reason"] for r in body["recent"]] == ["stop_loss", "take_profit"]


async def test_performance_is_empty_not_zero_shaped_without_closed_trades(client, seeded_orders):
    """Нээлттэй order нь хаагдсан арилжаа БИШ — нэгтгэлд орохгүй."""
    body = (await client.get("/api/v1/performance")).json()
    assert body["per_symbol"] == []
    assert body["recent"] == []
    assert body["net"] == "0.00"
    assert body["total"] == {"trades": 0, "net": "0.00"}


async def test_total_counts_every_close_not_just_the_prompt_window(client, db_session):
    """`net`/`per_symbol` нь prompt-ийн 20 мөрийн цонх. Самбар тэр цонхоор
    гарвал 21 дэх хаалтаас эхлэн хөшиж, хаалт бүр нэгийг чимээгүй түлхэнэ."""
    from datetime import timedelta

    from app import models
    from app.util.time import now_utc

    base = now_utc()
    db_session.add_all(
        [
            models.Order(
                client_order_id=f"p3-many-{i}",
                symbol="AAPL",
                side="sell",
                qty=Decimal("1"),
                order_type="market",
                time_in_force="day",
                status="filled",
                origin="research_agent",
                risk_evaluation={"decision": "APPROVE"},
                mode="paper",
                submitted_at=base + timedelta(minutes=i),
                filled_at=base + timedelta(minutes=i),
                realized_pl=Decimal("1.00"),
            )
            for i in range(21)
        ]
    )
    await db_session.commit()

    body = (await client.get("/api/v1/performance")).json()
    assert body["net"] == "20.00"  # цонх
    assert body["total"] == {"trades": 21, "net": "21.00"}  # бүх түүх
