"""FastAPI app factory (LLD §3).

Глобал синглтон БАЙХГҮЙ: app бүр өөрийн engine, broker, bus-тай. Тест нь
prod-ийн ЯГ энэ функцийг дуудна — тестэд зориулсан хоёр дахь угсралт байхгүй.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.envelope import MixedSourceError
from app.api.problem import ProblemError
from app.audit import logging as audit_logging
from app.broker.models import BrokerUnavailable, SystemState
from app.db import make_sessionmaker
from app.stream.bus import CHANNEL_SYSTEM, EventBus
from app.system.state import StateMachine

API_PREFIX = "/api/v1"


def create_app(*, engine, settings, broker, bus: EventBus | None = None) -> FastAPI:
    audit_logging.install()
    bus = bus or EventBus()
    sessionmaker = make_sessionmaker(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with sessionmaker() as session:
            machine = StateMachine(
                session,
                wind_down_grace=settings.WIND_DOWN_GRACE,
                publisher=app.state.publish_system,
            )
            # Дахин асаалт нь төлөвийг УНШИНА, эхлүүлэхгүй (AC-37).
            row = await machine.ensure_initialised()
            app.state.current_state = row.state
        yield

    app = FastAPI(
        title="PERSONAL-3 Alpaca Trading System — Operator API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.broker = broker
    app.state.bus = bus
    app.state.sessionmaker = sessionmaker
    app.state.current_state = SystemState.HALTED

    async def publish_system(payload: dict) -> None:
        await bus.publish(CHANNEL_SYSTEM, payload)

    app.state.publish_system = publish_system

    # Broker-ийн envelope дэх `system_state` нь ХҮСЭЛТИЙН эхэнд уншсан утга —
    # нэг хариу дотор хоёр өөр төлөв харагдахгүй (LLD §4).
    if hasattr(broker, "bind_system_state"):
        broker.bind_system_state(lambda: app.state.current_state)

    from app.api import (
        routes_agents,
        routes_approvals,
        routes_orders,
        routes_read,
        routes_system,
        routes_tuning,
        ws,
    )

    for module in (
        routes_read,
        routes_orders,
        routes_approvals,
        routes_system,
        routes_agents,
        routes_tuning,
    ):
        app.include_router(module.router, prefix=API_PREFIX)
    app.include_router(ws.router)

    @app.exception_handler(ProblemError)
    async def _problem_handler(_request, exc: ProblemError):
        return exc.response()

    @app.exception_handler(BrokerUnavailable)
    async def _broker_handler(_request, exc: BrokerUnavailable):
        return ProblemError("broker_unavailable", 503, str(exc)).response()

    @app.exception_handler(MixedSourceError)
    async def _mixed_source_handler(_request, exc: MixedSourceError):
        # Гэрээний зөрчил нь 500 — клиентэд «хэсэгчилсэн» хариу буцаахгүй.
        return JSONResponse(status_code=500, content={"code": "mixed_source", "detail": str(exc)})

    return app


def build() -> FastAPI:  # pragma: no cover - uvicorn-ийн орох цэг
    from app.config.settings import get_settings
    from app.db import init_engine

    settings = get_settings()
    engine = init_engine(settings.DATABASE_URL)
    from app.broker.alpaca import AlpacaAdapter

    broker = AlpacaAdapter(
        mode=settings.mode,
        api_key=settings.ALPACA_API_KEY,
        api_secret=settings.ALPACA_API_SECRET,
        stale_after_seconds=settings.STALE_AFTER_SECONDS,
    )
    return create_app(engine=engine, settings=settings, broker=broker)
