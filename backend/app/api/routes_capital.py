"""Profit-cut endpoint-ууд (хувийн төсөл, LLD-д тусгаагүй).

`POST /capital/withdraw` бол operator өөрөө хийж буй үйлдэл — эрсдэл
нэмэгдүүлэхгүй (эсрэгээрээ, риск-ийн сав багасгана) тул `routes_orders.py`-
ийн ESCALATE-ийн хоёр шаттай баталгаажуулалт ХЭРЭГГҮЙ. Гэхдээ бусад
operator-ийн үйлдэл шиг `AuditChain`-д бичигдэнэ (`app.capital.ledger`).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from app.api.deps import SessionDep, StateMachineDep
from app.api.envelope import envelope, money_field
from app.api.problem import problem
from app.api.routes_read import current_source
from app.capital.ledger import InvalidWithdrawal, total_withdrawn, withdraw

router = APIRouter()


class WithdrawBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str | None = None
    pct: str | None = None
    note: str | None = None


def _decimal(value: str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise problem("invalid_request", 422, f"{field}: тоон утга биш — {value!r}") from exc


@router.post("/capital/withdraw", operation_id="postCapitalWithdraw")
async def post_capital_withdraw(
    request: Request, machine: StateMachineDep, session: SessionDep, body: WithdrawBody
):
    broker = request.app.state.broker
    try:
        row = await withdraw(
            session,
            broker,
            amount=_decimal(body.amount, "amount"),
            pct=_decimal(body.pct, "pct"),
            note=body.note,
        )
    except InvalidWithdrawal as exc:
        raise problem("invalid_request", 422, str(exc)) from exc

    state = await machine.current()
    return envelope(
        {
            "withdrawal": {
                "id": str(row.id),
                "amount": money_field(row.amount),
                "pct": str(row.pct) if row.pct is not None else None,
                "equity_at_withdrawal": money_field(row.equity_at_withdrawal),
                "note": row.note,
            }
        },
        source=current_source(request),
        system_state=state.state,
    )


@router.get("/capital/summary", operation_id="getCapitalSummary")
async def get_capital_summary(request: Request, machine: StateMachineDep, session: SessionDep):
    broker = request.app.state.broker
    equity = (await broker.get_account()).data.equity
    withdrawn = await total_withdrawn(session)
    state = await machine.current()
    return envelope(
        {
            "broker_equity": money_field(equity),
            "total_withdrawn": money_field(withdrawn),
            "effective_equity": money_field(equity - withdrawn),
        },
        source=current_source(request),
        system_state=state.state,
    )
