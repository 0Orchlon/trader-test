"""Алдааны бүх хариу нь `Problem` гэрээг хангана (N-2, N-3, LLD §9.1).

Хоёр нүх байв:

- **N-2** — FastAPI-ийн анхдагч validation хариу нь `{"detail": [...]}` тул
  `code` талбаргүй. Frontend нь ЗӨВХӨН `code`-оор салаалдаг: код байхгүй
  хариу нь «үл мэдэгдэх алдаа» болж, operator-т шалтгаан харагдахгүй.
- **N-3** — Alpaca-ийн 403 (wash trade, buying power) нь `broker_unavailable`
  503 болж буудаг байв. «Broker унасан» гэсэн худал оношилгоо: operator
  дахин оролдоно, мөн breaker-ийн уналтын метрик бохирдоно.
"""
from __future__ import annotations

import uuid

import pytest

from tests.fakes import quote
from tests.helpers import activate

URL = "/api/v1/orders/manual"

VALID = {
    "symbol": "AAPL",
    "side": "buy",
    "qty": "10",
    "order_type": "limit",
    "time_in_force": "day",
    "limit_price": "221.50",
}


def _headers() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture
def problem_codes() -> set[str]:
    """Гэрээний enum — чөлөөт текст код нэмэх нь гэрээний зөрчил."""
    from pathlib import Path

    import yaml

    contract = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    return set(contract["components"]["schemas"]["Problem"]["properties"]["code"]["enum"])


def _assert_problem(payload: dict, status: int, codes: set[str]) -> None:
    for field in ("type", "title", "status", "code"):
        assert field in payload, f"Problem-д `{field}` алга: {payload}"
    assert payload["status"] == status
    assert payload["code"] in codes, f"гэрээнд байхгүй код: {payload['code']}"


# --- N-2: validation ---


async def test_a_malformed_body_returns_problem_json_with_a_code(client, problem_codes):
    response = await client.post(URL, json={"symbol": "AAPL"}, headers=_headers())
    assert response.status_code == 422
    _assert_problem(response.json(), 422, problem_codes)
    assert response.json()["code"] == "invalid_request"
    # Аль талбар нурсныг operator харах ёстой — «алдаа гарлаа» хангалтгүй.
    assert response.json()["errors"], "унасан талбаруудын жагсаалт алга"


async def test_a_missing_idempotency_header_is_also_a_problem(client, problem_codes):
    response = await client.post(URL, json=VALID)
    assert response.status_code == 422
    _assert_problem(response.json(), 422, problem_codes)
    assert response.json()["code"] == "invalid_request"


async def test_a_bad_path_parameter_is_also_a_problem(client, problem_codes):
    response = await client.post("/api/v1/orders/not-a-uuid/cancel")
    assert response.status_code == 422
    _assert_problem(response.json(), 422, problem_codes)


# --- N-3: broker-ийн татгалзал ---


async def test_a_broker_rejection_is_not_reported_as_an_outage(client, broker, problem_codes):
    from app.broker.models import BrokerRejected

    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    broker.fail_submit = BrokerRejected(
        "potential wash trade detected", broker_code="42210000", status=403
    )

    response = await client.post(URL, json=VALID, headers=_headers())

    assert response.status_code == 422, response.text
    _assert_problem(response.json(), 422, problem_codes)
    assert response.json()["code"] == "broker_rejected"
    assert response.json()["broker_code"] == "42210000"


async def test_a_real_outage_is_still_503(client, broker, problem_codes):
    from app.broker.models import BrokerUnavailable

    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    broker.fail_submit = BrokerUnavailable("Alpaca хүрэхгүй")

    response = await client.post(URL, json=VALID, headers=_headers())
    assert response.status_code == 503
    _assert_problem(response.json(), 503, problem_codes)
    assert response.json()["code"] == "broker_unavailable"


async def test_a_synchronous_rejection_counts_towards_the_reject_rate(client, broker, db_session):
    """Alpaca руу хүрсэн ч татгалзсан order нь reject метрикт ОРНО (LLD §15.2).

    Энэ order хэзээ ч trade-update үүсгэхгүй тул WS зам түүнийг тоолохгүй —
    тоолуургүй бол дараалсан татгалзал breaker-ийг хэзээ ч унагаахгүй.
    """
    from sqlalchemy import select

    from app import models
    from app.broker.models import BrokerRejected

    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    await activate(client)
    broker.fail_submit = BrokerRejected("wash trade", broker_code="42210000", status=403)

    await client.post(URL, json=VALID, headers=_headers())

    rows = (
        await db_session.execute(
            select(models.BreakerEvent).where(models.BreakerEvent.kind == "order_reject")
        )
    ).scalars().all()
    assert [r.ok for r in rows] == [False]
