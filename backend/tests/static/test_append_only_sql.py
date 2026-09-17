"""Append-only хамгаалалтын статик хаалга (N-1 · LLD §5.7, §5.8).

Тест нь SQLite дээр ажилладаг тул энэ файлын DDL нь БОДИТООР ажиллахгүй —
тиймээс агуулгыг нь шалгана. Хоёр зүйл чухал:

1. `DO INSTEAD NOTHING` нь UPDATE-ыг **чимээгүй** залгина: дуудагч амжилттай
   гэж үзээд цааш явна. Append-only хүснэгт дээр энэ нь алдаанаас ДОР.
2. `TRUNCATE` нь RULE-ээр баригддаггүй бөгөөд `REVOKE ... FROM PUBLIC` нь
   эзэн/superuser-т нөлөөгүй. Түүнийг зөвхөн `BEFORE TRUNCATE` trigger барина.
"""
from __future__ import annotations

from pathlib import Path

import pytest

SQL = (
    Path(__file__).resolve().parents[2] / "migrations" / "postgres_append_only.sql"
).read_text(encoding="utf-8")

#: Тайлбар мөрүүдгүй эх — шалгалт нь ажиллах DDL-ийг хардаг, тайлбарыг биш.
STATEMENTS = "\n".join(
    line for line in SQL.splitlines() if not line.lstrip().startswith("--")
).upper()

APPEND_ONLY_TABLES = ("audit_log", "system_state")


def test_no_silent_swallow():
    assert "DO INSTEAD NOTHING" not in STATEMENTS


def test_mutations_raise():
    assert "RAISE EXCEPTION" in STATEMENTS


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
@pytest.mark.parametrize("operation", ("UPDATE", "DELETE", "TRUNCATE"))
def test_each_mutation_is_refused_by_a_trigger(table: str, operation: str):
    upper = STATEMENTS
    needle = f"BEFORE {operation} ON {table.upper()}"
    assert needle in upper, f"{table}: {operation}-ийг хаасан trigger алга"
