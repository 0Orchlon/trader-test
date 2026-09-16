"""`tuning_history` + хүний хаалттай promote (T-28, LLD §21, AC-22…AC-24).

`applies_to` нь ҮРГЭЛЖ `paper` гэж эхэлнэ. `live` болох **цорын ганц зам**
нь operator-ийн `POST /tuning/promote` + хоёр шаттай баталгаажуулалт.
Ямар ч модель, ямар ч автомат job үүнийг хийж ЧАДАХГҮЙ — энэ модульд
`approved_by="system"` + `applies_to="live"` хослол үүсгэх салаа БАЙХГҮЙ.

Walk-forward нотолгоо ЗААВАЛ: `folds`, in-sample БА out-of-sample метрик
хоёулаа байх ёстой. Хоосон нотолгоотой мөрийг дэвшүүлэх нь «шалгагдсан»
гэсэн худал баталгаа өгнө.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.audit.chain import AuditChain
from app.tuning.whitelist import load as load_whitelist
from app.util.time import now_utc, to_iso

PAPER = "paper"
LIVE = "live"
SYSTEM = "system"
OPERATOR = "operator"

REQUIRED_WALK_FORWARD_KEYS = ("folds", "in_sample_metric", "out_of_sample_metric")


class MissingEvidence(ValueError):
    """Walk-forward нотолгоо дутуу — дэвшүүлэх боломжгүй."""


@dataclass(frozen=True, slots=True)
class ParameterState:
    name: str
    current_value: Decimal
    applies_to: str
    history: list[models.TuningHistory]


def _valid_evidence(walk_forward: dict | None) -> bool:
    if not isinstance(walk_forward, dict):
        return False
    return all(walk_forward.get(k) not in (None, "") for k in REQUIRED_WALK_FORWARD_KEYS)


async def record_tuning(
    session: AsyncSession,
    *,
    parameter: str,
    old_value: Decimal,
    new_value: Decimal,
    bounds: dict,
    walk_forward: dict,
    backtest_window: dict | None = None,
) -> models.TuningHistory:
    """Автомат тохируулгын мөр. `applies_to` нь ҮРГЭЛЖ `paper`."""
    if not _valid_evidence(walk_forward):
        raise MissingEvidence(
            f"{parameter}: walk-forward нотолгоо дутуу — {REQUIRED_WALK_FORWARD_KEYS}"
        )
    row = models.TuningHistory(
        parameter=parameter,
        old_value=str(old_value),
        new_value=str(new_value),
        bounds=bounds,
        backtest_window=backtest_window,
        walk_forward=walk_forward,
        applies_to=PAPER,
        approved_by=SYSTEM,
        changed_at=now_utc(),
    )
    session.add(row)
    await session.flush()
    await AuditChain(session).append(
        "tuning_applied",
        f"system:auto_tuning",
        {
            "tuning_history_id": str(row.id),
            "parameter": parameter,
            "old_value": str(old_value),
            "new_value": str(new_value),
            "applies_to": PAPER,
            "walk_forward": walk_forward,
        },
    )
    return row


async def history_for(session: AsyncSession, parameter: str) -> list[models.TuningHistory]:
    return list(
        (
            await session.execute(
                select(models.TuningHistory)
                .where(models.TuningHistory.parameter == parameter)
                .order_by(models.TuningHistory.changed_at)
            )
        ).scalars()
    )


async def parameter_states(session: AsyncSession) -> list[ParameterState]:
    """Whitelist × түүх → одоогийн утга ба `applies_to`.

    Түүхгүй параметрийн утга нь config-ийн `default` — «мэдэгдэхгүй» гэсэн
    гурав дахь байдал БАЙХГҮЙ.
    """
    out: list[ParameterState] = []
    for spec in load_whitelist().values():
        rows = await history_for(session, spec.name)
        latest = rows[-1] if rows else None
        out.append(
            ParameterState(
                name=spec.name,
                current_value=Decimal(latest.new_value) if latest else spec.default,
                applies_to=latest.applies_to if latest else PAPER,
                history=rows,
            )
        )
    return out


async def promote(
    session: AsyncSession, ids: list[uuid.UUID], *, actor: str = OPERATOR
) -> list[models.TuningHistory]:
    """Paper-т шалгагдсан мөрүүдийг `live` рүү. ЗӨВХӨН хүн дуудна."""
    promoted: list[models.TuningHistory] = []
    chain = AuditChain(session)
    for row_id in ids:
        row = await session.get(models.TuningHistory, row_id)
        if row is None:
            raise LookupError(f"tuning_history олдсонгүй: {row_id}")
        if not _valid_evidence(row.walk_forward):
            raise MissingEvidence(f"{row.parameter}: walk-forward нотолгоо дутуу")
        if row.applies_to == LIVE:
            continue  # идемпотент
        # Шинэ МӨР — хуучныг засахгүй. Түүх нь append-only (AC-17-ийн сүнс).
        live_row = models.TuningHistory(
            parameter=row.parameter,
            old_value=row.old_value,
            new_value=row.new_value,
            bounds=row.bounds,
            backtest_window=row.backtest_window,
            walk_forward=row.walk_forward,
            applies_to=LIVE,
            approved_by=OPERATOR,
            changed_at=now_utc(),
        )
        session.add(live_row)
        await session.flush()
        await chain.append(
            "tuning_promoted",
            actor,
            {
                "source_tuning_history_id": str(row.id),
                "tuning_history_id": str(live_row.id),
                "parameter": row.parameter,
                "new_value": row.new_value,
                "walk_forward": row.walk_forward,
                "promoted_at": to_iso(live_row.changed_at),
            },
        )
        promoted.append(live_row)
    await session.commit()
    return promoted
