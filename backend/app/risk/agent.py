"""Risk Agent — детерминистик хаалга (LLD §8, FR-3).

`evaluate()` нь **ЦЭВЭР ФУНКЦ**: I/O БАЙХГҮЙ, цаг унших БАЙХГҮЙ, random
БАЙХГҮЙ. Бүх оролт `RiskContext`-д. Тиймээс 10 000 property кейс нь DB-гүй,
секундын дотор ажиллана (AC-4, AC-35).

`ValidatedOrder`-ыг үүсгэх ЦОРЫН ГАНЦ газар нь энэ модулийн `APPROVE` салаа.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.broker.models import (
    Account,
    OrderIntent,
    Position,
    Quote,
    RiskDecision,
    SystemState,
    ValidatedOrder,
)
from app.execution.idempotency import derive_client_order_id
from app.risk.limits import RiskLimits
from app.risk.rules import Check, ESCALATING_RULES, REJECTING_RULES
from app.util.time import to_iso


@dataclass(frozen=True, slots=True)
class RiskContext:
    """Дүрмийн БҮХ оролт энд. Далд төлөв байхгүй тул mutation testing утгатай."""

    account: Account
    positions: list[Position]
    quote: Quote | None
    day_trade_count: int
    system_state: SystemState
    limits: RiskLimits
    now: datetime
    #: `client_order_id`-ийн деривацийн үндэс (LLD §9.2). Детерминистик.
    idempotency_key: str = ""


@dataclass(frozen=True, slots=True)
class RiskEvaluation:
    decision: RiskDecision
    reason: str | None
    checks: list[Check]
    evaluated_at: datetime
    validated_order: ValidatedOrder | None = None

    def to_contract(self) -> dict:
        """contracts.yaml `RiskEvaluation`."""
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "evaluated_at": to_iso(self.evaluated_at),
            "checks": [
                {
                    k: v
                    for k, v in {
                        "rule": c.rule,
                        "passed": c.passed,
                        "limit_name": c.limit_name,
                        "limit_value": c.limit_value,
                        "actual_value": c.actual_value,
                        "detail": c.detail,
                    }.items()
                    if v is not None or k in ("rule", "passed")
                }
                for c in self.checks
            ],
        }


def evaluate(ctx: RiskContext, req: OrderIntent) -> RiskEvaluation:
    checks: list[Check] = []
    failed: list[Check] = []
    for rule in REJECTING_RULES:
        check = rule(ctx, req)
        checks.append(check)
        if not check.passed:
            failed.append(check)

    escalations: list[Check] = []
    for rule in ESCALATING_RULES:
        check = rule(ctx, req)
        checks.append(check)
        if not check.passed:
            escalations.append(check)

    # REJECT нь ESCALATE-ээс ДАВУУ — хоёул унавал REJECT (LLD §8.1).
    if failed:
        return RiskEvaluation(
            decision=RiskDecision.REJECT,
            reason=_reason(failed),
            checks=checks,
            evaluated_at=ctx.now,
        )
    if escalations:
        return RiskEvaluation(
            decision=RiskDecision.ESCALATE_TO_HUMAN,
            reason=_reason(escalations),
            checks=checks,
            evaluated_at=ctx.now,
        )

    evaluation = RiskEvaluation(
        decision=RiskDecision.APPROVE,
        reason=None,
        checks=checks,
        evaluated_at=ctx.now,
    )
    # APPROVE салаа — Risk-ийн харсан утгууд ЭНД хөлддөг.
    validated = ValidatedOrder(
        symbol=req.symbol,
        side=req.side,
        qty=req.qty,
        order_type=req.order_type,
        time_in_force=req.time_in_force,
        limit_price=req.limit_price,
        stop_price=req.stop_price,
        client_order_id=derive_client_order_id(ctx.idempotency_key, req),
        risk_evaluation=evaluation.to_contract(),
    )
    return RiskEvaluation(
        decision=RiskDecision.APPROVE,
        reason=None,
        checks=checks,
        evaluated_at=ctx.now,
        validated_order=validated,
    )


def _reason(failed: list[Check]) -> str:
    parts = []
    for check in failed:
        if check.rule == "system_state":
            parts.append(f"system_state={check.actual_value} (halted үед шинэ order илгээхгүй)")
        elif check.detail and check.actual_value is None:
            parts.append(f"{check.rule}: {check.detail}")
        else:
            parts.append(
                f"{check.rule}: {check.actual_value} vs {check.limit_name} {check.limit_value}"
            )
    return "; ".join(parts)
