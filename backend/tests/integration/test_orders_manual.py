"""T-08 (ID=635) · T-47 (ID=672) — гарын order-ийн зам (AC-31…AC-33).

Энэ зам нь agent-ийн замтай ЯГ ИЖИЛ хаалгыг дайрна: Risk Agent → Execution →
Alpaca. «Operator өөрөө шүү дээ» гэсэн үндэслэлээр богино зам БАЙХГҮЙ.

DoD-ийн голууд:
- `halted`       → 409, Alpaca руу **уншилт ч, бичилт ч 0** дуудалт.
- Risk REJECT    → 422, submit 0.
- `winding_down` → нэмэгдүүлэх татгалзана, багасгах дамжина.
- ESCALATE       → 409 `confirmation_required`; ЯГ ижил биетэй token-той
                   дахин илгээвэл дамжина. Approval queue-д мөр ҮҮСГЭХГҮЙ.
- Idempotency    → ижил key + ижил бие = нэг order; ижил key + өөр бие = 409.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app import models
from tests.fakes import position, quote
from tests.helpers import activate, wind_down

URL = "/api/v1/orders/manual"


def body(**overrides) -> dict:
    base = {
        "symbol": "AAPL",
        "side": "buy",
        "qty": "10",
        "order_type": "limit",
        "time_in_force": "day",
        "limit_price": "221.50",
    }
    base.update(overrides)
    return base


def headers(key: str | None = None) -> dict:
    return {"Idempotency-Key": key or str(uuid.uuid4())}


async def post(client, payload: dict | None = None, *, key: str | None = None):
    return await client.post(URL, json=payload or body(), headers=headers(key))


# --- AC-33: төлөвийн хараат байдал ---


async def test_halted_rejects_without_touching_alpaca(client, broker):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    response = await post(client)
    assert response.status_code == 409
    assert response.json()["code"] == "system_halted"
    assert broker.submitted == []
    # AC-33: уншилт ч хийгдэхгүй — Risk контекст угсрах хүртэл ч очихгүй.
    assert broker.calls == []


async def test_winding_down_blocks_exposure_increase(client, broker):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    await wind_down(client)
    response = await post(client)
    assert response.status_code == 422
    assert response.json()["code"] == "winding_down_increase_blocked"
    assert broker.submitted == []


async def test_winding_down_allows_position_reduction(client, broker):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    broker.positions = [position("AAPL", "40", "8860.00")]
    await activate(client)
    await wind_down(client)
    response = await post(client, body(side="sell", qty="10"))
    assert response.status_code == 202, response.text
    assert len(broker.submitted) == 1


# --- AC-31: Risk-ийн шийдвэр ---


async def test_risk_reject_returns_422_and_never_reaches_alpaca(client, broker):
    broker.quotes["GME"] = quote("GME", "20.00")
    await activate(client)
    response = await post(client, body(symbol="GME", limit_price="20.00"))
    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "risk_rejected"
    # Operator юу унасныг БҮХЭЛД нь харна — есөн шалгалт бүгд биед.
    rules = {c["rule"] for c in payload["risk"]["checks"]}
    assert "restricted_symbol" in rules and len(rules) == 9
    assert broker.submitted == []


async def test_no_quote_rejects(client, broker):
    """Мэдэхгүй байдал нь зөвшөөрөл БИШ (LLD §8.3)."""
    await activate(client)
    response = await post(client, body(order_type="market", limit_price=None))
    assert response.status_code == 422
    assert broker.submitted == []


async def test_approve_submits_with_manual_origin(client, broker, db_session):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    response = await post(client)
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["order"]["origin"] == "manual_operator"
    assert payload["order"]["origin_detail"] == "operator"
    assert payload["risk"]["decision"] == "APPROVE"
    assert payload["source"] == "alpaca_paper"
    assert len(broker.submitted) == 1


async def test_manual_order_creates_no_agent_decision(client, broker, db_session):
    """AC-32 — гарын order нь agent-ийн санал БИШ."""
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    await post(client)
    count = (
        await db_session.execute(select(func.count(models.AgentDecision.id)))
    ).scalar_one()
    assert count == 0


async def test_manual_order_is_audited_with_actor(client, broker, db_session):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    await post(client)
    rows = (
        await db_session.execute(
            select(models.AuditLog).where(models.AuditLog.event_type == "order_submitted")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor == "operator"
    assert rows[0].payload["origin"] == "manual_operator"


# --- AC-31: хоёр шаттай баталгаажуулалт (approval queue-гүй) ---


async def test_escalation_asks_for_confirmation_then_submits(client, broker, db_session):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    big = body(qty="30")  # 30 × 221.50 = 6645 > MAX_ORDER_NOTIONAL 5000
    key = str(uuid.uuid4())

    first = await client.post(URL, json=big, headers=headers(key))
    assert first.status_code == 409
    assert first.json()["code"] == "confirmation_required"
    assert broker.submitted == []
    # Спек A-8: approval queue-д мөр ҮҮСГЭХГҮЙ — operator өөрөө энд байна.
    approvals = (await db_session.execute(select(func.count(models.Approval.id)))).scalar_one()
    assert approvals == 0

    token = first.json()["confirmation"]["token"]
    second = await client.post(URL, json={**big, "confirmation_token": token}, headers=headers(key))
    assert second.status_code == 202, second.text
    assert len(broker.submitted) == 1


async def test_confirmation_token_does_not_cover_a_changed_body(client, broker):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    first = await client.post(URL, json=body(qty="30"), headers=headers())
    token = first.json()["confirmation"]["token"]
    tampered = {**body(qty="40"), "confirmation_token": token}
    second = await client.post(URL, json=tampered, headers=headers())
    assert second.status_code == 409
    assert second.json()["code"] == "confirmation_required"
    assert broker.submitted == []


# --- T-08: idempotency ---


async def test_same_key_same_body_submits_once(client, broker):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    key = str(uuid.uuid4())
    first = await post(client, key=key)
    second = await post(client, key=key)
    assert first.status_code == second.status_code == 202
    assert first.json()["order"]["id"] == second.json()["order"]["id"]
    assert len(broker.submitted) == 1


async def test_same_key_different_body_is_conflict(client, broker):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    key = str(uuid.uuid4())
    await post(client, key=key)
    conflict = await post(client, body(qty="11"), key=key)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
    assert len(broker.submitted) == 1


async def test_idempotency_key_header_is_required(client):
    response = await client.post(URL, json=body())
    assert response.status_code == 422


# --- цуцлалт ---


async def test_cancel_forwards_to_broker(client, broker, seeded_orders):
    order = [o for o in seeded_orders if o.status == "accepted"][0]
    response = await client.post(f"/api/v1/orders/{order.id}/cancel")
    assert response.status_code == 202
    assert broker.canceled == [order.broker_order_id]


async def test_cancel_is_allowed_while_halted(client, broker, seeded_orders):
    """Спек A-2 — kill switch нь ШИНЭ order-ыг зогсоодог, цуцлалтыг биш."""
    order = [o for o in seeded_orders if o.status == "accepted"][0]
    await client.post("/api/v1/kill-switch", json={})
    response = await client.post(f"/api/v1/orders/{order.id}/cancel")
    assert response.status_code == 202
    assert broker.canceled == [order.broker_order_id]


async def test_cancel_unknown_order_is_404(client):
    response = await client.post(f"/api/v1/orders/{uuid.uuid4()}/cancel")
    assert response.status_code == 404
