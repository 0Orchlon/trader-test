"""Арилжааг ЗӨВХӨН логоос сэргээх (T-25, LLD §14.4, AC-18).

`audit_log`-оос өөр ХҮСНЭГТЭД ХҮРЭХГҮЙ. Энэ бол хязгаарлалт биш, шалгалт:
хэрэв энд `orders`-ийг уншвал «лог өөрөө бүрэн үү» гэдэг асуулт хариугүй
үлдэнэ. Тест нь гаралтыг `orders`/`fills`-тэй тулгаж бүрэн эсэхийг батална.

Сэргээх зүйл: ямар санал, ямар өгөгдлөөр үндэслэгдсэн, Risk юу шийдсэн,
хэн зөвшөөрсөн, юу илгээгдсэн, юу биелсэн.

    python -m app.audit.replay --from 2026-09-16T00:00:00Z
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.util.time import to_iso

#: Энэ скриптийн ойлгодог үйл явдлууд. Шинэ төрөл нэмэх нь ЭНД бүртгэгдэнэ —
#: үл таних төрөл нь чимээгүй алдагдахгүй, `unknown_events`-д гарна.
KNOWN_EVENTS = (
    "agent_decision",
    "order_submitted",
    "order_failed",
    "order_cancel_requested",
    "approval_resolved",
    "approval_expired",
    "state_changed",
    "provider_switched",
    "reconciliation_drift",
    "tuning_applied",
    "tuning_promoted",
    "capital_withdrawn",
)


@dataclass
class OrderStory:
    """Нэг order-ийн бүрэн түүх — зөвхөн логоос."""

    client_order_id: str
    symbol: str | None = None
    side: str | None = None
    qty: str | None = None
    origin: str | None = None
    origin_detail: str | None = None
    mode: str | None = None
    broker_order_id: str | None = None
    risk_decision: str | None = None
    submitted_at: str | None = None
    failure_reason: str | None = None
    canceled: bool = False
    #: Энэ order-ыг үүсгэсэн шийдвэр (байвал).
    decision_id: str | None = None
    rationale: str | None = None
    grounded_in: list[str] = field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    approved_by: str | None = None

    def to_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Replay:
    orders: dict[str, OrderStory] = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)
    state_changes: list[dict] = field(default_factory=list)
    approvals: list[dict] = field(default_factory=list)
    provider_switches: list[dict] = field(default_factory=list)
    tuning_changes: list[dict] = field(default_factory=list)
    withdrawals: list[dict] = field(default_factory=list)
    unknown_events: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "orders": [s.to_json() for s in self.orders.values()],
            "decisions": self.decisions,
            "state_changes": self.state_changes,
            "approvals": self.approvals,
            "provider_switches": self.provider_switches,
            "tuning_changes": self.tuning_changes,
            "withdrawals": self.withdrawals,
            "unknown_events": sorted(set(self.unknown_events)),
        }


def _story(replay: Replay, client_order_id: str) -> OrderStory:
    return replay.orders.setdefault(client_order_id, OrderStory(client_order_id))


def reduce_events(rows) -> Replay:
    """Цэвэр функц: (seq, ts, event_type, actor, payload) → `Replay`.

    DB-гүй тул тест нь бүтээсэн мөрүүд дээр шууд ажиллана.
    """
    replay = Replay()
    # Шийдвэрийг order-той холбохын тулд decision_id → мөр.
    by_decision: dict[str, dict] = {}

    for row in rows:
        event, payload, ts = row.event_type, row.payload or {}, row.ts
        if event not in KNOWN_EVENTS:
            replay.unknown_events.append(event)
            continue

        if event == "agent_decision":
            record = {
                "at": to_iso(ts),
                "actor": row.actor,
                **{
                    k: payload.get(k)
                    for k in (
                        "decision_id", "provider", "model", "symbol", "side", "qty",
                        "rationale", "grounded_in", "grounding", "risk", "outcome",
                    )
                },
            }
            replay.decisions.append(record)
            if payload.get("decision_id"):
                by_decision[str(payload["decision_id"])] = record

        elif event == "order_submitted":
            story = _story(replay, str(payload.get("client_order_id")))
            story.symbol = payload.get("symbol")
            story.side = payload.get("side")
            story.qty = payload.get("qty")
            story.origin = payload.get("origin")
            story.origin_detail = payload.get("origin_detail")
            story.mode = payload.get("mode")
            story.broker_order_id = payload.get("broker_order_id")
            story.submitted_at = to_iso(ts)
            story.risk_decision = (payload.get("risk_evaluation") or {}).get("decision")
            # Agent-ийн order бол origin_detail = provider/model.
            if story.origin == "research_agent" and story.origin_detail:
                story.provider, _, story.model = story.origin_detail.partition("/")
            _attach_decision(story, replay)

        elif event == "order_failed":
            story = _story(replay, str(payload.get("client_order_id")))
            story.failure_reason = payload.get("reason")

        elif event == "order_cancel_requested":
            for story in replay.orders.values():
                if story.broker_order_id == payload.get("broker_order_id"):
                    story.canceled = True

        elif event in ("approval_resolved", "approval_expired"):
            replay.approvals.append({"at": to_iso(ts), "actor": row.actor, **payload})

        elif event == "state_changed":
            replay.state_changes.append({"at": to_iso(ts), "actor": row.actor, **payload})

        elif event == "provider_switched":
            replay.provider_switches.append({"at": to_iso(ts), **payload})

        elif event in ("tuning_applied", "tuning_promoted"):
            replay.tuning_changes.append(
                {"at": to_iso(ts), "kind": event, "actor": row.actor, **payload}
            )

        elif event == "capital_withdrawn":
            replay.withdrawals.append({"at": to_iso(ts), "actor": row.actor, **payload})

    return replay


def _attach_decision(story: OrderStory, replay: Replay) -> None:
    """Symbol + provider-ээр хамгийн сүүлийн таарах шийдвэрийг холбоно.

    Таарах шийдвэр ОЛДООГҮЙ бол талбарууд `None` хэвээр — «хамгийн ойрын»
    шийдвэрт наах таамаг БАЙХГҮЙ (LLD D-1-тэй ижил зарчим).
    """
    for record in reversed(replay.decisions):
        if record.get("symbol") != story.symbol:
            continue
        if story.provider and record.get("provider") != story.provider:
            continue
        story.decision_id = record.get("decision_id")
        story.rationale = record.get("rationale")
        story.grounded_in = list(record.get("grounded_in") or [])
        story.provider = story.provider or record.get("provider")
        story.model = story.model or record.get("model")
        return


async def replay_from_log(
    session: AsyncSession, *, since: datetime | None = None, until: datetime | None = None
) -> Replay:
    stmt = select(models.AuditLog).order_by(models.AuditLog.seq)
    if since is not None:
        stmt = stmt.where(models.AuditLog.ts >= since)
    if until is not None:
        stmt = stmt.where(models.AuditLog.ts <= until)
    rows = list((await session.execute(stmt)).scalars())
    return reduce_events(rows)


async def _main() -> int:  # pragma: no cover - CLI
    import argparse

    from app.config.settings import get_settings
    from app.db import init_engine, make_sessionmaker
    from app.util.time import parse_iso

    parser = argparse.ArgumentParser(description="Арилжааг зөвхөн audit_log-оос сэргээх")
    parser.add_argument("--from", dest="since", default=None)
    parser.add_argument("--to", dest="until", default=None)
    args = parser.parse_args()

    engine = init_engine(get_settings().DATABASE_URL)
    async with make_sessionmaker(engine)() as session:
        result = await replay_from_log(
            session,
            since=parse_iso(args.since) if args.since else None,
            until=parse_iso(args.until) if args.until else None,
        )
    await engine.dispose()
    print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(asyncio.run(_main()))
