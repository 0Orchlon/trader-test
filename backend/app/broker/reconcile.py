"""EOD reconciliation (T-10, LLD §7, AC-13).

Зах зээл хаагдсаны дараа локал `orders` ↔ Alpaca-ийн тайлагнасан төлөвийг
тулгана.

**Alpaca нь эх сурвалж.** Зөрүүг локал тооцооллоор «засахгүй» — Alpaca-ийн
утгыг ХУУЛНА. Локал талыг «зөв» гэж үзэх нь системийг өөрийн буруу зурагт
түгжинэ (хавсралт 02 §6).

Зөрүү бүр `audit_log`-д `reconciliation_drift` болж бичигдэнэ. Нийт зөрүү
`RECONCILE_DRIFT_LIMIT`-ээс их бол breaker унана: тоолуур чимээгүй өсөх нь
энэ системд хамгийн удаан далдлагдах эвдрэл.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.audit.chain import AuditChain
from app.broker.models import OPEN_ORDER_STATUSES, BrokerOrder
from app.util.time import now_utc

LOCAL_OPEN_STATUSES = tuple(s.value for s in OPEN_ORDER_STATUSES) + ("pending_risk",)


@dataclass(frozen=True, slots=True)
class Drift:
    kind: str
    client_order_id: str | None
    local: str | None
    broker: str | None

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "client_order_id": self.client_order_id,
            "local": self.local,
            "broker": self.broker,
        }


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    drifts: list[Drift] = field(default_factory=list)
    breaker_tripped: bool = False

    @property
    def count(self) -> int:
        return len(self.drifts)

    def to_json(self) -> dict:
        return {
            "drift_count": self.count,
            "drifts": [d.to_json() for d in self.drifts],
            "breaker_tripped": self.breaker_tripped,
        }


def _compare(local_rows: list[models.Order], broker_orders: list[BrokerOrder]) -> list[Drift]:
    """Зөвхөн ХАРЬЦУУЛНА — цэвэр функц, тест нь DB-гүй ажиллана."""
    by_client = {o.client_order_id: o for o in broker_orders if o.client_order_id}
    drifts: list[Drift] = []

    for row in local_rows:
        remote = by_client.pop(row.client_order_id, None)
        if remote is None:
            # Локал «нээлттэй», Alpaca дээр байхгүй: хаагдсан ба бид алдсан.
            drifts.append(Drift("missing_at_broker", row.client_order_id, row.status, None))
            continue
        if remote.status.value != row.status:
            drifts.append(
                Drift("status_mismatch", row.client_order_id, row.status, remote.status.value)
            )
        elif remote.filled_qty != row.filled_qty:
            drifts.append(
                Drift(
                    "filled_qty_mismatch",
                    row.client_order_id,
                    str(row.filled_qty),
                    str(remote.filled_qty),
                )
            )

    for client_order_id, remote in by_client.items():
        # Alpaca дээр нээлттэй, локалд мөргүй: UI-аас гараар нээсэн байж болно.
        drifts.append(Drift("unknown_locally", client_order_id, None, remote.status.value))
    return drifts


async def reconcile(session: AsyncSession, broker, *, settings, publisher=None) -> ReconcileReport:
    local_rows = list(
        (
            await session.execute(
                select(models.Order).where(models.Order.status.in_(LOCAL_OPEN_STATUSES))
            )
        ).scalars()
    )
    broker_orders = list((await broker.get_open_orders()).data)
    drifts = _compare(local_rows, broker_orders)

    if not drifts:
        # Зөрүүгүй бол ямар ч тоолуур ахихгүй — «бүх юм хэвийн» гэдэг нь
        # чимээгүй байдал биш, хэмжигдсэн үр дүн.
        return ReconcileReport()

    by_client = {o.client_order_id: o for o in broker_orders if o.client_order_id}
    local_by_client = {o.client_order_id: o for o in local_rows}
    for drift in drifts:
        if drift.kind in ("status_mismatch", "filled_qty_mismatch"):
            row = local_by_client[drift.client_order_id]
            remote = by_client[drift.client_order_id]
            # Alpaca-ийн утгыг ХУУЛНА, тооцохгүй.
            row.status = remote.status.value
            row.filled_qty = remote.filled_qty
            row.filled_at = remote.filled_at or row.filled_at

    chain = AuditChain(session)
    await chain.append(
        "reconciliation_drift",
        "system:scheduler",
        {"at": now_utc().isoformat(), "drift_count": len(drifts), "drifts": [d.to_json() for d in drifts]},
    )
    await session.commit()

    tripped = False
    if len(drifts) > int(settings.RECONCILE_DRIFT_LIMIT):
        from app.broker.models import SystemState
        from app.system.state import StateMachine

        machine = StateMachine(
            session, wind_down_grace=settings.WIND_DOWN_GRACE, publisher=publisher
        )
        if (await machine.current()).state is not SystemState.HALTED:
            await machine.transition(
                SystemState.HALTED,
                by="circuit_breaker",
                reason=f"reconciliation_drift={len(drifts)} > RECONCILE_DRIFT_LIMIT={settings.RECONCILE_DRIFT_LIMIT}",
            )
        tripped = True

    return ReconcileReport(drifts=drifts, breaker_tripped=tripped)
