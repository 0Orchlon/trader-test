"""T-26 (653) whitelist · T-27 (654) bounded search · T-28 (655) promote.

Голууд:
- Муж нь config-оос; API-аар ӨӨРЧЛӨХ endpoint БАЙХГҮЙ (AC-24).
- Хайлт нь муж + `step`-ээр хязгаарлагдана; гадуурх утга гарч ирэхгүй.
- Out-of-sample сайжралгүй бол санал үүсэхгүй (curve-fitting-ийн хаалт).
- `live` болох цорын ганц зам нь хүний `promote` + баталгаажуулалт.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import models
from app.tuning import promote as promote_mod
from app.tuning.search import search
from app.tuning.walkforward import MIN_FOLDS, NotEnoughData, run as walk_forward, split
from app.tuning.whitelist import load as load_whitelist, lookup

SERIES = list(range(24))


def peaked_at(target: Decimal):
    """`target`-т хамгийн өндөр, түүнээс холдох тусам буурах детерминистик
    метрик. Backtest engine-гүйгээр хайлтын зан төлөвийг барина."""

    def evaluate(window, value: Decimal) -> Decimal:
        return Decimal("10") - abs(Decimal(value) - target)

    return evaluate


# --- T-26: whitelist ба муж ---


def test_every_parameter_declares_min_max_step_and_default():
    for spec in load_whitelist().values():
        assert spec.minimum < spec.maximum
        assert spec.step > 0
        assert spec.contains(spec.default), spec.name


def test_a_value_outside_the_range_is_refused():
    spec = lookup("STOP_LOSS_PCT")
    assert not spec.contains(Decimal("0.9"))
    assert not spec.contains(Decimal("5.1"))


def test_a_value_off_the_step_grid_is_refused():
    """«Муж дотор л шүү дээ» гэдэг нь хангалтгүй — алхам ч хязгаар."""
    spec = lookup("STOP_LOSS_PCT")
    assert spec.contains(Decimal("2.5"))
    assert not spec.contains(Decimal("2.55"))


def test_the_grid_is_finite_and_inside_the_bounds():
    grid = lookup("STOP_LOSS_PCT").grid()
    assert grid[0] == Decimal("1.0") and grid[-1] == Decimal("5.0")
    assert all(Decimal("1.0") <= v <= Decimal("5.0") for v in grid)


async def test_there_is_no_endpoint_that_changes_the_bounds(client, app):
    """AC-24 — муж өөрчлөх нь deploy, API биш."""
    paths = {route.path for route in app.routes}
    assert "/api/v1/tuning/parameters" in paths
    forbidden = [p for p in paths if "tuning" in p and p.endswith(("/bounds", "/whitelist"))]
    assert forbidden == []
    for method in ("put", "patch", "delete"):
        response = await getattr(client, method)("/api/v1/tuning/parameters")
        assert response.status_code == 405


# --- T-27: walk-forward ---


def test_a_single_fold_is_not_walk_forward():
    with pytest.raises(NotEnoughData):
        split(SERIES, MIN_FOLDS - 1)


def test_too_little_data_is_refused_instead_of_padded():
    with pytest.raises(NotEnoughData):
        split([1, 2], 4)


def test_folds_never_train_on_the_future():
    for train, test in split(SERIES, 4):
        assert max(train) < min(test)


def test_both_metrics_are_recorded():
    """Сайныг нь л харуулах нь curve-fitting-ийг далдална (LLD §21)."""
    result = walk_forward(SERIES, Decimal("2.5"), peaked_at(Decimal("2.5")), folds=3)
    contract = result.to_contract()
    assert contract["folds"] == 3
    assert contract["in_sample_metric"] and contract["out_of_sample_metric"]


# --- T-27: bounded search ---


def test_the_search_never_leaves_the_grid():
    spec = lookup("STOP_LOSS_PCT")
    result = search(
        spec, SERIES, peaked_at(Decimal("99")), current_value=Decimal("2.5"), folds=3
    )
    assert result.has_proposal
    assert result.best.value in spec.grid()
    assert result.best.value == spec.maximum


def test_no_proposal_when_the_current_value_is_already_best():
    spec = lookup("STOP_LOSS_PCT")
    result = search(
        spec, SERIES, peaked_at(Decimal("2.5")), current_value=Decimal("2.5"), folds=3
    )
    assert not result.has_proposal
    assert result.reason  # шалтгаан нь ИЛ, чимээгүй хоосон үр дүн биш


def test_a_proposal_moves_toward_the_better_value():
    spec = lookup("STOP_LOSS_PCT")
    result = search(
        spec, SERIES, peaked_at(Decimal("3.5")), current_value=Decimal("2.5"), folds=3
    )
    assert result.has_proposal and result.best.value == Decimal("3.5")


def test_a_value_that_collapses_in_one_fold_is_not_proposed():
    """Дунджаар сайн ч НЭГ fold дээр нурсан нь стратеги БИШ.

    3.5 нь дунджаар суурь утгаас илүү — тиймээс «сайжралгүй» хаалгыг
    давна. Гэвч сүүлийн fold-ын out-of-sample нурсан тул санал үүсэхгүй.
    """
    spec = lookup("STOP_LOSS_PCT")

    def unstable(window, value: Decimal) -> Decimal:
        if Decimal(value) != Decimal("3.5"):
            return Decimal("0")
        return Decimal("-30") if window[0] == 18 else Decimal("40")

    result = search(spec, SERIES, unstable, current_value=Decimal("2.5"), folds=3)
    assert not result.has_proposal
    assert "curve-fitting" in result.reason


# --- T-28: tuning_history + promote ---


async def seed_history(db_session, *, walk_forward_evidence: dict | None = None):
    row = await promote_mod.record_tuning(
        db_session,
        parameter="STOP_LOSS_PCT",
        old_value=Decimal("2.5"),
        new_value=Decimal("2.6"),
        bounds=lookup("STOP_LOSS_PCT").to_json(),
        walk_forward=walk_forward_evidence
        or {"folds": 3, "in_sample_metric": "sharpe=1.31", "out_of_sample_metric": "sharpe=1.08"},
    )
    await db_session.commit()
    return row


async def test_an_automatic_change_is_always_paper(db_session):
    """AC-23 — модель ХЭЗЭЭ Ч live-д хүрэхгүй."""
    row = await seed_history(db_session)
    assert row.applies_to == "paper"
    assert row.approved_by == "system"


async def test_a_change_without_walk_forward_evidence_is_refused(db_session):
    with pytest.raises(promote_mod.MissingEvidence):
        await promote_mod.record_tuning(
            db_session,
            parameter="STOP_LOSS_PCT",
            old_value=Decimal("2.5"),
            new_value=Decimal("2.6"),
            bounds=lookup("STOP_LOSS_PCT").to_json(),
            walk_forward={"folds": 3},
        )


async def test_the_current_value_falls_back_to_the_config_default(db_session):
    states = {s.name: s for s in await promote_mod.parameter_states(db_session)}
    assert states["STOP_LOSS_PCT"].current_value == Decimal("2.5")
    assert states["STOP_LOSS_PCT"].applies_to == "paper"


async def test_the_latest_history_row_becomes_the_current_value(db_session):
    await seed_history(db_session)
    states = {s.name: s for s in await promote_mod.parameter_states(db_session)}
    assert states["STOP_LOSS_PCT"].current_value == Decimal("2.6")


async def test_promote_requires_confirmation(client, db_session):
    row = await seed_history(db_session)
    first = await client.post(
        "/api/v1/tuning/promote", json={"tuning_history_ids": [str(row.id)]}
    )
    assert first.status_code == 409
    assert first.json()["code"] == "confirmation_required"
    assert "LIVE" in first.json()["confirmation"]["prompt"]
    await db_session.refresh(row)
    assert row.applies_to == "paper"


async def test_promote_with_a_token_writes_an_operator_approved_live_row(client, db_session):
    row = await seed_history(db_session)
    body = {"tuning_history_ids": [str(row.id)]}
    token = (await client.post("/api/v1/tuning/promote", json=body)).json()["confirmation"][
        "token"
    ]
    response = await client.post(
        "/api/v1/tuning/promote", json={**body, "confirmation_token": token}
    )
    assert response.status_code == 200
    promoted = response.json()["promoted"]
    assert promoted[0]["applies_to"] == "live"
    assert promoted[0]["approved_by"] == "operator"

    rows = (await db_session.execute(select(models.TuningHistory))).scalars().all()
    # Хуучин мөр ЗАСАГДААГҮЙ — түүх append-only.
    assert sorted(r.applies_to for r in rows) == ["live", "paper"]


async def test_promote_is_audited(client, db_session):
    row = await seed_history(db_session)
    body = {"tuning_history_ids": [str(row.id)]}
    token = (await client.post("/api/v1/tuning/promote", json=body)).json()["confirmation"][
        "token"
    ]
    await client.post("/api/v1/tuning/promote", json={**body, "confirmation_token": token})
    audits = (
        await db_session.execute(
            select(models.AuditLog).where(models.AuditLog.event_type == "tuning_promoted")
        )
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].actor == "operator"


async def test_promoting_an_unknown_row_is_404(client, db_session):
    body = {"tuning_history_ids": [str(uuid.uuid4())]}
    token = (await client.post("/api/v1/tuning/promote", json=body)).json()["confirmation"][
        "token"
    ]
    response = await client.post(
        "/api/v1/tuning/promote", json={**body, "confirmation_token": token}
    )
    assert response.status_code == 404


async def test_the_parameters_endpoint_shows_bounds_and_history(client, db_session):
    await seed_history(db_session)
    body = (await client.get("/api/v1/tuning/parameters")).json()
    by_name = {p["name"]: p for p in body["parameters"]}
    stop_loss = by_name["STOP_LOSS_PCT"]
    assert stop_loss["bounds"] == {"min": "1.0", "max": "5.0", "step": "0.1"}
    assert stop_loss["current_value"] == "2.6"
    assert stop_loss["history"][0]["walk_forward"]["folds"] == 3
