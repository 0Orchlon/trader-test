"""Арилжааны төлөвийн машин — OP-13-ийн цөм (LLD §6).

`ACTIVE` → `WINDING_DOWN` → `HALTED`. `HALTED`-аас гарах ЦОРЫН ГАНЦ зам нь
operator-ийн `activate`. `halted → winding_down` шилжилт ЗОРИУДААР БАЙХГҮЙ:
зогссоны дараах «бага зэрэг арилжаа» нь kill switch-ийн утгыг сулруулна.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.audit.chain import AuditChain
from app.broker.models import SystemState
from app.util.time import now_utc, to_iso

#: Кэшийн наслалт. Redis-д БИШ — process-дотоод (P-6).
CACHE_TTL_SECONDS = 0.2


class InvalidTransition(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class StateRow:
    seq: int
    state: SystemState
    reason: str | None
    changed_by: str
    changed_at: datetime
    wind_down_deadline: datetime | None

    @property
    def seconds_remaining(self) -> int | None:
        if self.state is not SystemState.WINDING_DOWN or self.wind_down_deadline is None:
            return None
        return max(0, int((self.wind_down_deadline - now_utc()).total_seconds()))


def _row(model: models.SystemStateRow) -> StateRow:
    return StateRow(
        seq=int(model.seq),
        state=SystemState(model.state),
        reason=model.reason,
        changed_by=model.changed_by,
        changed_at=model.changed_at,
        wind_down_deadline=model.wind_down_deadline,
    )


class StateMachine:
    def __init__(
        self,
        session: AsyncSession,
        *,
        wind_down_grace: timedelta,
        publisher=None,
    ) -> None:
        self.session = session
        self.wind_down_grace = wind_down_grace
        self.publisher = publisher
        self._cache: tuple[float, StateRow] | None = None

    # --- унших ---

    async def current(self) -> StateRow:
        """Хамгийн их `seq`-тэй мөр. Богино TTL-тэй process-дотоод кэш."""
        import time

        if self._cache is not None and time.monotonic() - self._cache[0] < CACHE_TTL_SECONDS:
            return self._cache[1]
        model = (
            await self.session.execute(
                select(models.SystemStateRow).order_by(models.SystemStateRow.seq.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if model is None:
            raise InvalidTransition("not_initialised", "system_state хоосон — ensure_initialised()")
        row = _row(model)
        self._cache = (time.monotonic(), row)
        return row

    async def ensure_initialised(self) -> StateRow:
        """Startup (LLD §6.3). Төлөвийг УНШИНА — эхлүүлэхгүй.

        Мөр байхгүй бол (анхны deploy) `halted`. Grace нь унтарсан хугацаанд
        дууссан бол сэрэхдээ `halted` — хуанлийн цаг (AC-37).
        """
        model = (
            await self.session.execute(
                select(models.SystemStateRow).order_by(models.SystemStateRow.seq.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if model is None:
            return await self._insert(
                SystemState.HALTED, by="operator", reason="initial_deploy", deadline=None
            )
        row = _row(model)
        if (
            row.state is SystemState.WINDING_DOWN
            and row.wind_down_deadline is not None
            and row.wind_down_deadline <= now_utc()
        ):
            return await self.transition(
                SystemState.HALTED, by="scheduler", reason="grace_expired_while_down"
            )
        return row

    # --- бичих ---

    async def transition(
        self,
        to: SystemState,
        *,
        by: str,
        reason: str | None,
        grace: timedelta | None = None,
    ) -> StateRow:
        current = await self.current()
        deadline = self._validate(current, to, grace)
        if deadline is _NO_OP:
            return current
        # `_insert` нь мөр + audit-ыг НЭГ транзакцид commit хийнэ.
        row = await self._insert(to, by=by, reason=reason, deadline=deadline)
        # Дараалал чухал: commit → ДАРАА нь нийтлэх (LLD §6.2).
        if self.publisher is not None:
            await self.publisher(
                {
                    "type": "state_changed",
                    "from": current.state.value,
                    "to": row.state.value,
                    "reason": row.reason,
                    "changed_by": row.changed_by,
                    "changed_at": to_iso(row.changed_at),
                    "wind_down_deadline": to_iso(row.wind_down_deadline),
                    "seconds_remaining": row.seconds_remaining,
                }
            )
        return row

    def _validate(self, current: StateRow, to: SystemState, grace: timedelta | None):
        if to is SystemState.WINDING_DOWN:
            if current.state is SystemState.HALTED:
                raise InvalidTransition("already_halted", "зогссон систем wind-down хийхгүй")
            if current.state is SystemState.WINDING_DOWN:
                return _NO_OP  # идемпотент, deadline СУНГАХГҮЙ
            return now_utc() + (self.wind_down_grace if grace is None else grace)
        if to is SystemState.ACTIVE:
            if current.state is SystemState.ACTIVE:
                raise InvalidTransition("already_active", "аль хэдийн идэвхтэй")
            return None
        if to is SystemState.HALTED:
            return None  # нөхцөлгүй; идемпотент бөгөөд мөр үлдээнэ
        raise InvalidTransition("unknown_state", f"тодорхойгүй төлөв: {to}")

    async def _insert(
        self, to: SystemState, *, by: str, reason: str | None, deadline: datetime | None
    ) -> StateRow:
        model = models.SystemStateRow(
            state=to.value,
            reason=reason,
            changed_by=by,
            changed_at=now_utc(),
            wind_down_deadline=deadline,
        )
        self.session.add(model)
        await self.session.flush()
        # Нэг транзакц: төлөвийн мөр ба audit мөр ХОЁУЛАА орно, эсвэл аль нь ч биш.
        await AuditChain(self.session).append(
            "state_changed",
            f"system:{by}" if by != "operator" else "operator",
            {
                "to": to.value,
                "reason": reason,
                "changed_by": by,
                "wind_down_deadline": to_iso(deadline),
            },
        )
        await self.session.commit()
        self._cache = None
        return _row(model)

    # --- scheduler ---

    async def sweep_expired_grace(self) -> StateRow | None:
        """10 секунд тутам (LLD §6.4). Давхардал идемпотент."""
        row = await self.current()
        if row.state is not SystemState.WINDING_DOWN or row.wind_down_deadline is None:
            return None
        if row.wind_down_deadline > now_utc():
            return None
        return await self.transition(
            SystemState.HALTED, by="scheduler", reason="wind_down_grace_expired"
        )


class _NoOp:
    pass


_NO_OP = _NoOp()
