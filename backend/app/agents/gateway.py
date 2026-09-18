"""Agent Gateway — tool dispatch (T-18, T-48, LLD §12.1, §12.4).

LLM нь ЭНД л системд хүрнэ. Дараалал (LLD §12.1) ТОГТМОЛ:

1. session-ийн provider-ийг тогтоох (солигдсон ч ЭНЭ дуудалт хуучнаар)
2. `tool_calls` INSERT → `tool_call_id`
3. handler ажиллуулах
4. `tool_calls` UPDATE — **хариу буцахаас ӨМНӨ** (INV-4)
5. `result_envelope` угсрах: `tool_call_id` + `timestamp` + `source`
   + `system_state` + `ok`/`error` + `data`
6. redact → adapter → LLM

**`system_state` нь tool result БҮРИЙН заавал талбар** (AC-34, T-48).
Нэмэлт мэдэгдлийн суваг БАЙХГҮЙ: LLM мэдэгдлийг үл тоомсорлож болох ч
tool result-гүйгээр ажиллаж чадахгүй. Тиймээс төлөв солигдсоны дараах
ЭХНИЙ tool result нь шинэ утгыг агуулна — agent мэдэлгүй үлдэх цонх байхгүй.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError

from app import models
from app.agents import contract
from app.audit.redact import redact
from app.broker.models import Source, SystemState
from app.util.time import now_utc, to_iso

#: LLM-д харуулах заавар. Машинд биш — МОДЕЛЬД зориулсан текст (LLD §12.4).
GUIDANCE = {
    SystemState.ACTIVE: (
        "Trading is active. Normal proposals are accepted; every proposal is still "
        "evaluated by the deterministic Risk Agent before anything is sent."
    ),
    SystemState.WINDING_DOWN: (
        "The operator is preparing to shut the machine down. Positions may only be "
        "reduced or closed. Any proposal that increases exposure will be rejected. "
        "Prioritise closing open positions before the grace period ends."
    ),
    SystemState.HALTED: (
        "Trading is halted. Every proposal will be rejected. Do not propose orders; "
        "only read tools are useful until the operator activates the system again."
    ),
}

ERROR_CODES = ("no_data", "stale", "unreachable", "invalid_symbol", "rate_limited")


class ToolError(Exception):
    """Ил алдаа. Талбар ОРХИХ замаар ХЭЗЭЭ Ч илэрхийлэхгүй (хавсралт 10 §2.4)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        if code not in ERROR_CODES:  # pragma: no cover - хөгжүүлэлтийн алдаа
            raise ValueError(f"гэрээнд байхгүй алдааны код: {code}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class StateView:
    """Tool result-д орох системийн төлөв (AC-34)."""

    state: SystemState
    seconds_remaining: int | None
    reason: str | None

    def to_json(self) -> dict:
        return {
            "state": self.state.value,
            "seconds_remaining": self.seconds_remaining,
            "reason": self.reason,
            "guidance": GUIDANCE[self.state],
        }


def envelope(
    tool_call_id: uuid.UUID,
    *,
    source: Source,
    state: StateView,
    ok: bool,
    data: dict | None = None,
    error: dict | None = None,
) -> dict:
    return {
        "tool_call_id": str(tool_call_id),
        "timestamp": to_iso(now_utc()),
        "source": Source(source).value,
        "system_state": state.to_json(),
        "ok": ok,
        "data": data,
        "error": error,
    }


def validate_input(tool_name: str, args: dict) -> None:
    """Гэрээний `input_schema`-аар. Гараар бичсэн шалгалт БАЙХГҮЙ."""
    try:
        Draft202012Validator(contract.input_schema(tool_name)).validate(args)
    except SchemaError as exc:
        raise ToolError("no_data", f"{tool_name}: схемийн алдаа — {exc.message}") from exc


class Gateway:
    """Handler-ийн dispatch. Handler бүр `async (ctx, args) -> dict`.

    Handler-ууд `app.agents.tools`-д. Тэднийг энд бүртгэснээр «LLM-д ямар
    гадаргуу нээлттэй вэ» гэдэг НЭГ жагсаалт болно (T-18 DoD а).
    """

    def __init__(
        self,
        session,
        handlers: dict,
        *,
        source: Source,
        provider_id: str,
        session_id: str,
        read_only: bool = False,
    ) -> None:
        self.session = session
        self.handlers = handlers
        self.source = source
        self.provider_id = provider_id
        self.session_id = session_id
        self.read_only = read_only

    def available(self) -> list[str]:
        names = contract.tool_names(read_only=self.read_only)
        return [n for n in names if n in self.handlers]

    async def dispatch(self, tool_name: str, args: dict, state: StateView, ctx: Any) -> dict:
        call = models.ToolCall(
            decision_id=None,
            session_id=self.session_id,
            tool_name=tool_name,
            request=redact(args),
            source=Source(self.source).value,
            provider=self.provider_id,
            called_at=now_utc(),
        )
        self.session.add(call)
        await self.session.flush()

        started = now_utc()
        ok, data, error = True, None, None
        try:
            if tool_name not in self.available():
                # INV-5: `read_only` provider-т бичих tool ОГТ байхгүй.
                raise ToolError("unreachable", f"{tool_name}: энэ provider-т нээлттэй биш")
            validate_input(tool_name, args)
            data = await self.handlers[tool_name](ctx, args)
        except ToolError as exc:
            ok, error = False, {"code": exc.code, "message": exc.message}

        # INV-4: хариу LLM рүү буцахаас ӨМНӨ бичигдэнэ.
        call.response = redact({"ok": ok, "data": data, "error": error})
        call.latency_ms = int((now_utc() - started).total_seconds() * 1000)
        await self.session.commit()

        return envelope(
            call.id, source=self.source, state=state, ok=ok, data=data, error=error
        )


async def state_view(machine) -> StateView:
    row = await machine.current()
    return StateView(
        state=row.state, seconds_remaining=row.seconds_remaining, reason=row.reason
    )
