"""Тоолуур нь УТАСЛАГДСАН эсэх (B-1 · LLD §15.2).

Adapter дээрх тоолуур ганцаараа хангалтгүй: `create_app` түүнийг DB рүү
бичдэг эх сурвалжтай холбохгүй бол `api_error_rate` үйлдвэрлэлд хоосон
хэвээр үлдэнэ. Энэ тест нь prod-ийн ЯГ тэр угсралтаар (create_app +
AlpacaAdapter) явж, `breaker_events`-д мөр үүссэнийг шалгана.
"""
from __future__ import annotations

import httpx
from sqlalchemy import select

from app import models
from app.broker.alpaca import AlpacaAdapter
from app.config.mode import TradingMode
from app.main import create_app


def _alpaca(handler) -> AlpacaAdapter:
    return AlpacaAdapter(
        mode=TradingMode.PAPER,
        api_key="k",
        api_secret="s",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://paper-api.alpaca.markets"
        ),
    )


async def test_system_state_records_broker_outage(engine, settings, bus, db_session):
    app = create_app(
        engine=engine,
        settings=settings,
        broker=_alpaca(lambda r: httpx.Response(503, json={})),
        bus=bus,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            body = (await client.get("/api/v1/system/state")).json()

    rows = (
        await db_session.execute(
            select(models.BreakerEvent).where(models.BreakerEvent.kind == "api_error")
        )
    ).scalars().all()
    assert rows, "broker унасан атлаа `api_error` мөр бичигдээгүй"
    assert all(row.ok is False for row in rows)

    # Тэр ижил хариунд метрик нь «0.0000 · унаагүй» БИШ, бодит уналт.
    metric = next(m for m in body["breaker_metrics"] if m["metric"] == "api_error_rate")
    assert metric["value"] == "1.0000"
    assert metric["tripped"] is True
