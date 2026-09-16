"""Request scope-ийн хамаарлууд (LLD §3).

Төлөвийн машин, broker, bus, settings нь `app.state`-д; session нь хүсэлт
тутам. Глобал синглтон БАЙХГҮЙ — тест бүр өөрийн app-тай.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.models import SystemState
from app.system.state import StateMachine


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_settings(request: Request):
    return request.app.state.settings


def get_broker(request: Request):
    return request.app.state.broker


def get_bus(request: Request):
    return request.app.state.bus


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_state_machine(request: Request, session: SessionDep) -> StateMachine:
    machine = StateMachine(
        session,
        wind_down_grace=request.app.state.settings.WIND_DOWN_GRACE,
        publisher=request.app.state.publish_system,
    )
    # Broker-ийн envelope нь `system_state`-ыг синхроноор уншина. Хүсэлт бүрд
    # ЭНД шинэчилж өгснөөр «нэг хариунд хоёр өөр төлөв» гэсэн байдал үүсэхгүй.
    row = await machine.current()
    request.app.state.current_state = row.state
    return machine


StateMachineDep = Annotated[StateMachine, Depends(get_state_machine)]


async def get_system_state(machine: StateMachineDep) -> SystemState:
    return (await machine.current()).state
