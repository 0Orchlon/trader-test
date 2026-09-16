"""T-02 (ID=629) + T-44 (ID=669) — DB schema."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect

from app.db import Base, make_engine
from app import models  # noqa: F401  — метадата бүртгэгдэнэ

EXPECTED_TABLES = {
    "accounts",
    "orders",
    "fills",
    "agent_decisions",
    "tool_calls",
    "tuning_history",
    "audit_log",
    "system_state",
    "approvals",
    "confirmations",
}


async def test_all_tables_created(db_session):
    engine = db_session.bind

    def _names(conn):
        return set(inspect(conn).get_table_names())

    async with engine.connect() as conn:
        names = await conn.run_sync(_names)
    assert EXPECTED_TABLES <= names


def test_orders_origin_is_not_null_and_has_no_default():
    """LLD §5.2 / AC-29 — анхдагч утга нь «мэдэхгүй»-г «мэднэ» болгоно."""
    col = models.Order.__table__.c.origin
    assert col.nullable is False
    assert col.default is None and col.server_default is None


async def test_origin_required_on_insert(db_session):
    from sqlalchemy.exc import IntegrityError

    from app.util.time import now_utc

    db_session.add(
        models.Order(
            client_order_id="p3-noorigin",
            symbol="AAPL",
            side="buy",
            qty="1",
            order_type="market",
            time_in_force="day",
            status="pending_risk",
            risk_evaluation={},
            mode="paper",
            submitted_at=now_utc(),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_system_state_history_is_append_only_by_seq(db_session):
    from app.util.time import now_utc

    for state in ("halted", "active", "winding_down"):
        db_session.add(
            models.SystemStateRow(
                state=state, reason="test", changed_by="operator", changed_at=now_utc()
            )
        )
        await db_session.flush()
    rows = (await db_session.execute(models.SystemStateRow.__table__.select())).all()
    assert [r.state for r in sorted(rows, key=lambda r: r.seq)] == [
        "halted",
        "active",
        "winding_down",
    ]
