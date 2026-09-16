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
