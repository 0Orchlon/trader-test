"""EOD reconciliation (T-10, LLD §7, AC-13).

Зах зээл хаагдсаны дараа локал `orders` ↔ Alpaca-ийн тайлагнасан төлөвийг
тулгана. Тулгалт нь НЭЭЛТТЭЙ order-ийн жагсаалтаар ХЯЗГААРЛАГДАХГҮЙ: мөр
бүрийг `client_order_id`-аар нь асууна, эс тэгвээс биелчихсэн (терминал)
orphan энэ ажилд бүтцээрээ үл үзэгдэнэ.

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
from app.broker.models import OPEN_ORDER_STATUSES, BrokerOrder, OrderStatus
from app.util.time import now_utc

#: `failed` нь энд САНААТАЙ: `ExecutionAgent._fail` нь timeout дээр мөрийг
#: `failed`, filled_qty 0 гэж бичдэг ч order Alpaca дээр АМЬД эсвэл БИЕЛСЭН
#: байж болно. Тулгахгүй бол тэр мөр үүрд худал үлдэж, exit manager-ийн
#: цэвэр bielelt агентын эзэмшлийг илүү харуулна.
LOCAL_OPEN_STATUSES = tuple(s.value for s in OPEN_ORDER_STATUSES) + (
    "pending_risk",
    OrderStatus.FAILED.value,
)


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


async def _broker_truth(
    broker, local_rows: list[models.Order], broker_orders: list[BrokerOrder]
) -> dict[str, BrokerOrder | None]:
    """`client_order_id` → broker-ийн мэдэгдсэн order, эсвэл `None` (байхгүй).

    `get_open_orders` нь `GET /v2/orders?status=open` — БИЕЛСЭН order тэнд
    тодорхойлолтоороо БАЙХГҮЙ. Тиймээс нээлттэй зурагт олдоогүй локал мөр
    БҮРИЙГ нэрээр нь (`client_order_id`) тусад нь асууна: тулгалтын гол
    мэдээ нь яг тэр — локалд «үхсэн» мөр broker дээр амьд эсвэл биелсэн байх.
    """
    by_client = {o.client_order_id: o for o in broker_orders if o.client_order_id}
    truth: dict[str, BrokerOrder | None] = {}
    for row in local_rows:
        remote = by_client.get(row.client_order_id)
        if remote is None:
            # ponytail: мөр тутамд нэг дуудалт — терминал БИШ локал мөр EOD-д
            # цөөхөн тул болно; олон зуу болвол багцлах хэрэгтэй.
            remote = await broker.get_order_by_client_id(row.client_order_id)
        truth[row.client_order_id] = remote
    return truth


def _compare(
    local_rows: list[models.Order],
    broker_orders: list[BrokerOrder],
    truth: dict[str, BrokerOrder | None],
) -> list[Drift]:
    """Зөвхөн ХАРЬЦУУЛНА — цэвэр функц, тест нь DB-гүй ажиллана.

    `truth` нь `_broker_truth`-ийн үр дүн (терминал order-ыг ч агуулна);
    `broker_orders` нь зөвхөн НЭЭЛТТЭЙ зураг — `unknown_locally`-д л хэрэгтэй.
    """
    local_ids = {row.client_order_id for row in local_rows}
    drifts: list[Drift] = []

    for row in local_rows:
        remote = truth.get(row.client_order_id)
        if remote is None:
            # `failed` мөр Alpaca дээр огт байхгүй нь ХҮЛЭЭГДСЭН — submit
            # хүрээгүй гэсэн үг. Үүнийг зөрүү гэж тоолбол хуучин алдаа бүр
            # өдөр бүр дахин тоологдож, breaker-ийг худлаар унагана. Мэдээ нь
            # ЭСРЭГ тохиолдол: тэр мөр broker дээр амьд/биелсэн байх.
            if row.status == OrderStatus.FAILED.value:
                continue
            # Локал «нээлттэй», Alpaca огт мэдэхгүй: submit хүрээгүй.
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

    for remote in broker_orders:
        # Alpaca дээр нээлттэй, локалд мөргүй: UI-аас гараар нээсэн байж болно.
        if remote.client_order_id and remote.client_order_id not in local_ids:
            drifts.append(
                Drift("unknown_locally", remote.client_order_id, None, remote.status.value)
            )
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
    truth = await _broker_truth(broker, local_rows, broker_orders)
    drifts = _compare(local_rows, broker_orders, truth)

    if not drifts:
        # Зөрүүгүй бол ямар ч тоолуур ахихгүй — «бүх юм хэвийн» гэдэг нь
        # чимээгүй байдал биш, хэмжигдсэн үр дүн.
        return ReconcileReport()

    local_by_client = {o.client_order_id: o for o in local_rows}
    for drift in drifts:
        row = local_by_client.get(drift.client_order_id)
        if row is None:
            continue  # `unknown_locally` — засах локал мөр байхгүй
        remote = truth.get(drift.client_order_id)
        if remote is not None:
            # Alpaca-ийн утгыг ХУУЛНА, тооцохгүй. Терминал order-т ч ижил:
            # эх сурвалж нь broker мөн бөгөөд «нээлттэй эсэх» нь түүнийг
            # өөрчлөхгүй.
            row.status = remote.status.value
            row.filled_qty = remote.filled_qty
            row.filled_at = remote.filled_at or row.filled_at
        else:
            # `missing_at_broker` нь ИЛРҮҮЛЭЭД ОРХИГДОЖ болохгүй: Alpaca энэ
            # order-ыг мэдэхгүй гэж ХАРИУЛСАН нь ч бас үнэн — тэр мөр хэзээ ч
            # биелэхгүй. «Нээлттэй» үлдээвэл exits тэр symbol-ыг ҮҮРД хаахаа
            # больж, зөрүү нь өдөр бүр дахин тоологдоно.
            row.status = OrderStatus.FAILED.value
            row.failure_reason = row.failure_reason or "reconcile: Alpaca дээр байхгүй"

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
