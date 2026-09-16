"""T-39 (ID=666) — paper proving window (AC-13).

DoD:
(а) метрик > 0 болгоход тоолуур 0-ээс дахин эхэлнэ;
(б) метрик > 0 байхад цонх ҮРГЭЛЖИЛСЭН хэвээр тоологдвол тест унана;
(в) тайлан нь RELEASE_APPROVAL-ийн нотолгоо болж гаргагдана.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.audit.chain import AuditChain
from app.system.proving import METRICS, REQUIRED_DAYS, measure
from app.util.time import now_utc


async def log_failure(db_session, event_type: str, at):
    """Тодорхой цагтай алдааны мөр. `AuditChain` нь `now_utc()` бичдэг тул
    цагийг дараа нь зориуд урагшлуулна (тест хүлээхгүй)."""
    row = await AuditChain(db_session).append(event_type, "system:test", {})
    row.ts = at
    await db_session.commit()
    return row


async def test_a_clean_window_passes(db_session):
    now = now_utc()
    window = await measure(db_session, started_at=now - timedelta(days=31), now=now)
    assert window.counts == {metric: 0 for metric in METRICS}
    assert window.clean_days == 31
    assert window.passed is True


@pytest.mark.parametrize("event_type", list(METRICS))
async def test_any_single_failure_resets_the_counter_to_zero(db_session, event_type):
    """(а) — метрик бүр ДАНГААРАА тоолуурыг тэглэнэ."""
    now = now_utc()
    await log_failure(db_session, event_type, now - timedelta(minutes=5))

    window = await measure(db_session, started_at=now - timedelta(days=31), now=now)
    assert window.counts[event_type] == 1
    assert window.clean_days == 0
    assert window.passed is False


async def test_the_window_does_not_keep_counting_through_a_failure(db_session):
    """(б) — 30 хоногийн 28 дээр гарсан алдаа нь 28 хоног БИШ."""
    now = now_utc()
    await log_failure(db_session, "reconciliation_drift", now - timedelta(days=2))

    window = await measure(db_session, started_at=now - timedelta(days=30), now=now)
    # Цонх нь 30 хоног ажилласан ч тоолуур нь сүүлийн алдаанаас хойш.
    assert window.clean_days == 2
    assert window.passed is False


async def test_the_counter_restarts_from_the_last_failure_not_the_first(db_session):
    now = now_utc()
    await log_failure(db_session, "grounding_failure", now - timedelta(days=20))
    await log_failure(db_session, "risk_limit_breach", now - timedelta(days=3))

    window = await measure(db_session, started_at=now - timedelta(days=40), now=now)
    assert window.clean_days == 3


async def test_a_long_clean_stretch_after_an_early_failure_passes(db_session):
    now = now_utc()
    await log_failure(db_session, "unhandled_exception", now - timedelta(days=REQUIRED_DAYS + 5))

    window = await measure(db_session, started_at=now - timedelta(days=60), now=now)
    assert window.clean_days == REQUIRED_DAYS + 5
    assert window.passed is True


async def test_the_report_is_release_approval_evidence(db_session):
    """(в) — тайлан нь бүх метрик, цонхны эхлэл, үр дүнг ил агуулна."""
    now = now_utc()
    await log_failure(db_session, "reconciliation_drift", now - timedelta(days=1))
    report = (await measure(db_session, started_at=now - timedelta(days=31), now=now)).to_json()

    assert report["required_days"] == REQUIRED_DAYS
    assert report["passed"] is False
    assert report["clean_days"] == 1
    assert set(report["counts"]) == set(METRICS)
    assert report["window_start"].endswith("Z")
    assert report["generated_at"].endswith("Z")
    assert report["failures"][0]["metric"] == "reconciliation_drift"


async def test_unrelated_audit_events_do_not_reset_the_counter(db_session):
    """Ердийн үйл ажиллагаа (order, state) нь алдаа БИШ."""
    now = now_utc()
    await log_failure(db_session, "order_submitted", now - timedelta(days=1))

    window = await measure(db_session, started_at=now - timedelta(days=31), now=now)
    assert window.clean_days == 31
    assert window.passed is True
