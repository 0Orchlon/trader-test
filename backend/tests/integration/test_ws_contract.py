"""WS гэрээний хаалга (B-2 засвар · asyncapi 1.1.0 · LLD §9.4, §12).

Хоёр давхарга:

1. Хаалга ӨӨРӨӨ ажиллаж байгааг батална (буруу payload УНАНА) — «үргэлж
   ногоон» шалгагч нь шалгагчгүйтэй адил.
2. WS-ээр ШУУД илгээгддэг (bus-аар ирдэггүй) хоёр frame — холболтын
   snapshot ба heartbeat — гэрээг хангана.

Bus-аар явдаг бүх нийтлэл нь `conftest`-ийн `ValidatingEventBus`-ээр
автоматаар шалгагдана. LLD §9.4-ийн `approval_created` нь `test_agents.py`-д
шалгагдана (escalation-ийн fixture тэнд байгаа).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.stream.bus import CHANNEL_ORDERS, CHANNEL_SYSTEM
from tests.asyncapi_schema import ContractViolation, validate


def test_validator_rejects_payload_that_violates_contract():
    with pytest.raises(ContractViolation):
        validate(CHANNEL_SYSTEM, {"seq": 1, "type": "state_changed"})  # `event` алга
    with pytest.raises(ContractViolation):
        validate(CHANNEL_ORDERS, {"seq": 1, "event": "order_submitted"})
    with pytest.raises(ContractViolation):
        validate("unknown-channel", {"seq": 1})


def test_ws_frames_sent_outside_the_bus_match_contract(app):
    """Snapshot ба heartbeat нь `websocket.send_json`-оор шууд явдаг."""
    app.state.settings.HEARTBEAT_SECONDS = 1
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()
        validate(snapshot["channel"], snapshot["payload"])
        assert snapshot["payload"]["event"] == "state_changed"
        heartbeat = ws.receive_json()
        validate(heartbeat["channel"], heartbeat["payload"])
        assert heartbeat["payload"]["event"] == "heartbeat"
