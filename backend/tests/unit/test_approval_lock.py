"""N-5 — approval-ийн шийдвэрлэлт нь мөрийг LOCK-лоно (LLD §15.3).

`session.get` + версь харьцуулалт нь атом БИШ: зэрэгцээ хоёр `approve`
хоёулаа шалгалтыг давж болно. Дедуп нь давхар order-оос аварч байгаа ч
«optimistic lock тул 409» гэсэн амлалт зэрэгцээ тохиолдолд баталгаагүй
байв. `SELECT ... FOR UPDATE` нь төлөвийн машинтай ИЖИЛ хэв маяг.
"""
from __future__ import annotations

import uuid


def test_approval_row_is_read_with_for_update():
    from sqlalchemy.dialects import postgresql

    from app.api.routes_approvals import locked_approval_stmt

    sql = str(locked_approval_stmt(uuid.uuid4()).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql.upper()
