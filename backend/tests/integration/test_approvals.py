"""T-17 (ID=644) — Approval queue (AC-5, AC-6).

DoD-ийн голууд:
- approve хүртэл Alpaca руу **0** дуудалт; reject-ийн дараа ч **0**.
- TTL дуусахад мөр `expired`; дууссан мөрийг approve хийх боломжгүй.
- `expected_version` нь optimistic lock — reaper-тэй уралдвал 409.

`approve` нь Risk-ийг ДАХИН ажиллуулна: TTL-ийн цонх дотор зах зээл хөдөлсөн
байж болно. Хөлдөөсөн шийдвэрийг сохроор гүйцэтгэх нь approval-ийн утгыг
алдагдуулна.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app import models
from app.approvals.queue import create_approval
from app.util.time import now_utc
from tests.fakes import position, quote
from tests.helpers import activate, wind_down


def proposal(**overrides) -> dict:
    base = {
        "symbol": "AAPL",
        "side": "buy",
        "qty": "30",
        "order_type": "limit",
        "limit_price": "221.50",
        "estimated_notional": "6645.00",
        "rationale": "Эзлэхүүнээр батлагдсан EMA огтлолцол",
        "grounded_in": [str(uuid.uuid4())],
        "provider": "claude-mcp",
        "model": "claude-opus-5",
    }
    base.update(overrides)
    return base


async def seed_decision(db_session, proposed: dict) -> models.AgentDecision:
    """Бодит `agent_decisions` мөр — `orders.decision_id` нь FK-тэй (N-4)."""
    row = models.AgentDecision(
        agent="research",
        provider="claude-mcp",
        model="claude-opus-5",
        session_id="sess-approvals",
        proposal=proposed,
        grounding={"passed": True, "unverified_claims": []},
        risk_evaluation={"decision": "ESCALATE_TO_HUMAN"},
        outcome="awaiting_approval",
        created_at=now_utc(),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def seed(db_session, *, ttl=timedelta(minutes=15), **overrides) -> models.Approval:
    proposed = proposal(**overrides)
    decision = await seed_decision(db_session, proposed)
    row = await create_approval(
        db_session,
        decision_id=decision.id,
        proposed_order=proposed,
        risk_evaluation={"decision": "ESCALATE_TO_HUMAN", "checks": [], "reason": "notional"},
        ttl=ttl,
    )
    await db_session.commit()
    return row


async def test_pending_approval_is_listed(client, db_session):
    row = await seed(db_session)
    body = (await client.get("/api/v1/approvals")).json()
    assert [a["id"] for a in body["approvals"]] == [str(row.id)]
    assert body["approvals"][0]["state"] == "pending"
    assert body["approvals"][0]["version"] == 1
    assert body["approvals"][0]["proposed_order"]["rationale"]


async def test_state_filter_hides_resolved_rows(client, db_session):
    row = await seed(db_session)
    await client.post(
        f"/api/v1/approvals/{row.id}/reject", json={"expected_version": 1, "reason": "болихгүй"}
    )
    assert (await client.get("/api/v1/approvals")).json()["approvals"] == []
    every = (await client.get("/api/v1/approvals?state=all")).json()["approvals"]
    assert [a["state"] for a in every] == ["rejected"]


# --- AC-5: approve-оос ӨМНӨ Alpaca руу 0 дуудалт ---


async def test_pending_approval_never_reaches_alpaca(client, broker, db_session):
    await seed(db_session)
    await client.get("/api/v1/approvals")
    assert broker.submitted == []


async def test_reject_never_submits_and_records_the_reason(client, broker, db_session):
    row = await seed(db_session)
    response = await client.post(
        f"/api/v1/approvals/{row.id}/reject",
        json={"expected_version": 1, "reason": "Үндэслэл хангалтгүй"},
    )
    assert response.status_code == 200
    assert broker.submitted == []
    await db_session.refresh(row)
    assert row.state == "rejected"
    assert row.resolution_reason == "Үндэслэл хангалтгүй"
    assert row.resolved_by == "operator"


async def test_rejected_row_can_never_be_approved(client, broker, db_session):
    row = await seed(db_session)
    await client.post(
        f"/api/v1/approvals/{row.id}/reject", json={"expected_version": 1, "reason": "үгүй"}
    )
    late = await client.post(f"/api/v1/approvals/{row.id}/approve", json={"expected_version": 2})
    assert late.status_code == 409
    assert broker.submitted == []


async def test_approve_submits_with_agent_origin(client, broker, db_session):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    row = await seed(db_session)
    response = await client.post(
        f"/api/v1/approvals/{row.id}/approve", json={"expected_version": 1, "note": "за"}
    )
    assert response.status_code == 202, response.text
    order = response.json()["order"]
    assert order["origin"] == "research_agent"
    assert order["origin_detail"] == "claude-mcp/claude-opus-5"
    assert order["decision_id"] == str(row.decision_id)
    assert len(broker.submitted) == 1
    await db_session.refresh(row)
    assert row.state == "approved" and row.resolved_by == "operator"


async def test_approve_twice_submits_once(client, broker, db_session):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    row = await seed(db_session)
    first = await client.post(f"/api/v1/approvals/{row.id}/approve", json={"expected_version": 1})
    assert first.status_code == 202
    second = await client.post(f"/api/v1/approvals/{row.id}/approve", json={"expected_version": 1})
    assert second.status_code == 409
    assert len(broker.submitted) == 1


async def test_version_conflict_is_409(client, db_session):
    row = await seed(db_session)
    response = await client.post(
        f"/api/v1/approvals/{row.id}/approve", json={"expected_version": 7}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"


# --- AC-6: TTL ---


async def test_expired_row_is_reaped_and_cannot_be_approved(client, broker, db_session):
    from app.approvals.reaper import expire_due

    row = await seed(db_session, ttl=timedelta(seconds=-1))
    assert await expire_due(db_session) == 1
    await db_session.refresh(row)
    assert row.state == "expired"
    assert row.version == 2
    assert row.resolution_reason == "expired"

    response = await client.post(
        f"/api/v1/approvals/{row.id}/approve", json={"expected_version": 2}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "approval_expired"
    assert broker.submitted == []


async def test_reaper_is_idempotent(db_session):
    from app.approvals.reaper import expire_due

    await seed(db_session, ttl=timedelta(seconds=-1))
    assert await expire_due(db_session) == 1
    assert await expire_due(db_session) == 0


async def test_approve_after_deadline_is_refused_even_before_the_reaper_runs(
    client, broker, db_session
):
    """Reaper бол цэвэрлэгээ, ХААЛГА биш — цаг нь эх сурвалж."""
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    row = await seed(db_session, ttl=timedelta(seconds=-1))
    response = await client.post(
        f"/api/v1/approvals/{row.id}/approve", json={"expected_version": 1}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "approval_expired"
    assert broker.submitted == []


# --- Risk нь approve дээр ДАХИН ажиллана ---


async def test_approve_reruns_risk_and_can_still_reject(client, broker, db_session):
    """TTL-ийн цонх дотор нөхцөл өөрчлөгдсөн бол approve гүйцэтгэхгүй."""
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    row = await seed(db_session)
    await client.post("/api/v1/kill-switch", json={"reason": "зогсоолоо"})
    response = await client.post(
        f"/api/v1/approvals/{row.id}/approve", json={"expected_version": 1}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "system_halted"
    assert broker.submitted == []
    await db_session.refresh(row)
    # Хаалга унасан бол мөр `pending` ХЭВЭЭР — operator дараа дахин үзнэ.
    assert row.state == "pending"


async def test_approve_of_an_exposure_increase_is_blocked_while_winding_down(
    client, broker, db_session
):
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    row = await seed(db_session)
    await wind_down(client)
    response = await client.post(
        f"/api/v1/approvals/{row.id}/approve", json={"expected_version": 1}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "winding_down_increase_blocked"
    assert broker.submitted == []


async def test_unknown_approval_is_404(client):
    response = await client.post(
        f"/api/v1/approvals/{uuid.uuid4()}/approve", json={"expected_version": 1}
    )
    assert response.status_code == 404
