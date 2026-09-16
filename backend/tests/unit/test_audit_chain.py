"""T-22 / T-23 (ID=650) — hash-chained audit log + verifier (AC-17, AC-19)."""
from __future__ import annotations

import pytest
from sqlalchemy import update

from app import models
from app.audit.chain import GENESIS_HASH, AuditChain, compute_hash
from app.audit.verifier import ChainBreak, verify_chain


async def _append_three(session) -> AuditChain:
    chain = AuditChain(session)
    await chain.append("order_submitted", "operator", {"symbol": "AAPL", "qty": "10"})
    await chain.append("kill_switch", "operator", {"reason": "тест"})
    await chain.append("state_changed", "system:state", {"to": "halted"})
    await session.commit()
    return chain


async def test_first_row_links_to_genesis(db_session):
    await _append_three(db_session)
    rows = (
        await db_session.execute(
            models.AuditLog.__table__.select().order_by(models.AuditLog.seq)
        )
    ).all()
    assert rows[0].prev_hash == GENESIS_HASH
    assert rows[1].prev_hash == rows[0].hash
    assert rows[2].prev_hash == rows[1].hash


async def test_verifier_passes_on_untouched_chain(db_session):
    await _append_three(db_session)
    assert await verify_chain(db_session) is None


async def test_verifier_reports_first_broken_seq(db_session):
    await _append_three(db_session)
    # Хэн нэгэн лог засав гэж үзье (Postgres дээр RULE татгалзана; SQLite дээр
    # боломжтой тул verifier-ийн ажлыг энд шалгана).
    await db_session.execute(
        update(models.AuditLog)
        .where(models.AuditLog.seq == 2)
        .values(payload={"reason": "өөрчлөгдсөн"})
    )
    await db_session.commit()
    result = await verify_chain(db_session)
    assert isinstance(result, ChainBreak)
    assert result.seq == 2


async def test_verify_from_seq_checks_tail_only(db_session):
    await _append_three(db_session)
    await db_session.execute(
        update(models.AuditLog).where(models.AuditLog.seq == 1).values(actor="хуурамч")
    )
    await db_session.commit()
    # Сүүлийн хэсгийг л шалгавал 1-ийн эвдрэл харагдахгүй — энэ нь зориуд.
    assert await verify_chain(db_session, from_seq=2) is None
    assert (await verify_chain(db_session)).seq == 1


def test_hash_is_canonical_regardless_of_key_order():
    from app.util.time import parse_iso

    ts = parse_iso("2026-09-16T14:30:00Z")
    a = compute_hash(GENESIS_HASH, 1, ts, "e", "actor", {"b": 2, "a": 1})
    b = compute_hash(GENESIS_HASH, 1, ts, "e", "actor", {"a": 1, "b": 2})
    assert a == b


async def test_payload_is_redacted_before_hashing(db_session):
    chain = AuditChain(db_session)
    await chain.append("provider_call", "system:gateway", {"api_key": "PKABCDEF1234567890"})
    await db_session.commit()
    row = (await db_session.execute(models.AuditLog.__table__.select())).first()
    assert "PKABCDEF1234567890" not in str(row.payload)
    assert await verify_chain(db_session) is None
