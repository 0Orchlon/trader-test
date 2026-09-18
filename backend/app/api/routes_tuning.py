"""Auto-tuning-ийн endpoint-ууд (T-26, T-28 · FR-10, AC-22…AC-24).

**Whitelist эсвэл bounds-ыг өөрчлөх endpoint ЭНД ЗОРИУДААР БАЙХГҮЙ.**
Муж нь `tuning_whitelist.yaml`-аас — өөрчлөх нь deploy + code review.
UI-аас муж өргөсгөх боломж нь SPEC_APPROVE-ийн хаалгыг тойрно (P-2).
`tests/static` дахь хаалга энэ маршрутын жагсаалтыг барина.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.confirm import consume, issue
from app.api.deps import SessionDep, StateMachineDep
from app.api.envelope import envelope
from app.api.problem import problem
from app.api.routes_read import current_source
from app.tuning.promote import MissingEvidence, parameter_states, promote
from app.tuning.whitelist import load as load_whitelist
from app.util.time import to_iso

router = APIRouter()


class PromoteBody(BaseModel):
    tuning_history_ids: list[uuid.UUID] = Field(min_length=1)
    confirmation_token: str | None = None


@router.get("/tuning/parameters", operation_id="getTuningParameters")
async def get_tuning_parameters(
    request: Request, machine: StateMachineDep, session: SessionDep
):
    specs = load_whitelist()
    states = await parameter_states(session)
    current = await machine.current()
    return envelope(
        {
            "parameters": [
                {
                    "name": state.name,
                    "current_value": str(state.current_value),
                    "bounds": specs[state.name].to_json(),
                    "applies_to": state.applies_to,
                    "history": [
                        {
                            "id": str(row.id),
                            "old_value": row.old_value,
                            "new_value": row.new_value,
                            "changed_at": to_iso(row.changed_at),
                            "approved_by": row.approved_by,
                            "backtest_window": row.backtest_window,
                            "walk_forward": row.walk_forward,
                        }
                        for row in state.history
                    ],
                }
                for state in states
            ]
        },
        source=current_source(request),
        system_state=current.state,
    )


@router.post("/tuning/promote", operation_id="postTuningPromote")
async def post_tuning_promote(
    request: Request, machine: StateMachineDep, session: SessionDep, body: PromoteBody
):
    """`paper` → `live`-ийн ЦОРЫН ГАНЦ зам. Хоёр шаттай баталгаажуулалт заавал."""
    settings = request.app.state.settings
    payload = {"tuning_history_ids": sorted(str(i) for i in body.tuning_history_ids)}

    if not body.confirmation_token:
        raise problem(
            "confirmation_required",
            409,
            "live рүү дэвшүүлэхийн өмнө ил баталгаажуулалт шаардлагатай",
            confirmation=await issue(
                session, "tuning_promote", payload, ttl=settings.CONFIRMATION_TTL
            ),
        )
    await consume(session, body.confirmation_token, "tuning_promote", payload)

    try:
        rows = await promote(session, list(body.tuning_history_ids))
    except MissingEvidence as exc:
        raise problem("confirmation_required", 409, str(exc)) from exc
    except LookupError as exc:
        raise problem("not_found", 404, str(exc)) from exc

    current = await machine.current()
    return envelope(
        {
            "promoted": [
                {
                    "id": str(row.id),
                    "parameter": row.parameter,
                    "new_value": row.new_value,
                    "applies_to": row.applies_to,
                    "approved_by": row.approved_by,
                    "changed_at": to_iso(row.changed_at),
                }
                for row in rows
            ]
        },
        source=current_source(request),
        system_state=current.state,
    )
