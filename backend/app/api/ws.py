"""WebSocket fan-out (T-04, LLD §12, AC-2, AC-14).

Нэг холболт, олон logical суваг (asyncapi). Холбогдмогц клиент **төлөвийн
хормын хувилбарыг** авна — «мессеж аваагүй тул бүх юм хэвийн» гэсэн таамаг
үүсэхгүй. `HEARTBEAT_SECONDS` тутам heartbeat; клиент 5 секунд чимээгүй
байвал stale banner гаргана.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import get_session
from app.stream.bus import CHANNEL_DECISIONS, CHANNEL_ORDERS, CHANNEL_SYSTEM, CHANNEL_TICKS
from app.system.state import StateMachine
from app.util.time import to_iso

router = APIRouter()

DEFAULT_CHANNELS = (CHANNEL_SYSTEM, CHANNEL_ORDERS, CHANNEL_DECISIONS, CHANNEL_TICKS)


async def _snapshot(app) -> dict:
    """Холбогдох агшны төлөв — REST-гүйгээр шууд."""
    async with app.state.sessionmaker() as session:
        machine = StateMachine(session, wind_down_grace=app.state.settings.WIND_DOWN_GRACE)
        row = await machine.current()
    return app.state.bus.stamp({
        "event": "state_changed",
        "state": row.state.value,
        "reason": row.reason,
        "wind_down_deadline": to_iso(row.wind_down_deadline),
        "seconds_remaining": row.seconds_remaining,
        "ts": to_iso(row.changed_at),
    })


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, channels: str | None = None) -> None:
    await websocket.accept()
    app = websocket.app
    bus = app.state.bus
    requested = [c.strip() for c in channels.split(",")] if channels else list(DEFAULT_CHANNELS)
    subscriber = bus.subscribe(requested)

    await websocket.send_json({"channel": CHANNEL_SYSTEM, "payload": await _snapshot(app)})

    heartbeat_seconds = app.state.settings.HEARTBEAT_SECONDS

    async def pump() -> None:
        while True:
            message = await subscriber.get()
            await websocket.send_json({"channel": message.channel, "payload": message.payload})

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(heartbeat_seconds)
            await websocket.send_json(
                {"channel": CHANNEL_SYSTEM, "payload": bus.stamp({"event": "heartbeat"})}
            )

    tasks = [asyncio.create_task(pump()), asyncio.create_task(heartbeat())]
    try:
        # Клиентийн хаалтыг сонсоно; орох мессежийг ашиглахгүй (зөвхөн receive).
        await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        bus.unsubscribe(subscriber)


__all__ = ["router", "get_session"]
