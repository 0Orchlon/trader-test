"""T-04 (ID=631) — WebSocket fan-out (AC-2, AC-14).

DoD (б): клиент салж дахин холбогдоход төлөв ДАХИН илгээгдэнэ.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.stream.bus import CHANNEL_SYSTEM


def test_client_receives_state_snapshot_on_connect(app):
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["channel"] == CHANNEL_SYSTEM
        assert first["payload"]["event"] == "state_changed"
        assert first["payload"]["state"] in ("active", "winding_down", "halted")


def test_reconnect_resends_state(app):
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["payload"]["event"] == "state_changed"


def test_published_system_event_reaches_client(app):
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()  # snapshot

        async def publish():
            await app.state.publish_system({"event": "kill_switch_engaged", "ts": "now"})

        client.portal.call(publish)
        message = ws.receive_json()
        assert message["payload"]["event"] == "kill_switch_engaged"


def test_tick_flood_does_not_starve_system_channel(app):
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()

        async def flood():
            for i in range(2000):
                await app.state.bus.publish("ticks:AAPL", {"symbol": "AAPL", "price": str(i)})
            await app.state.publish_system({"event": "wind_down_started"})

        client.portal.call(flood)
        # `system` нь эрэмбээр түрүүлнэ — tick-ийн үерт живэхгүй.
        assert ws.receive_json()["payload"]["event"] == "wind_down_started"
