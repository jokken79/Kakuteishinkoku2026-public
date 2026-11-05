"""Tests del motor de recomendaciones fiscales (節税アドバイザー) — plan 08.

Cubren el caso sintético (架空 太郎, perfil del `seed_dev_data`): 給与 + 副業
en pérdida (損益通算), 還付, dependiente SIN registrar y 住宅ローン控除 rechazado. Validan que el
motor genera al menos:

    1. Registrar a un familiar (老人扶養 別居) con ahorro > 0 (所得税 + 住民税).
    2. El 住宅ローン控除 rechazado no se aplica y pide verificar el motivo.
    3. La confirmación del 損益通算 (la pérdida del 副業 compensa el 給与).

Usan SQLite en memoria con el perfil sintético sembrado, sin dependencias externas.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import app
from app.models import Base
from app.models.entities import FilingDraft, JournalEntry
from app.seed.dev_seed import seed_dev_data


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Cliente de test con el PERFIL sintético (架空 太郎) sembrado.

    Yields:
        `TestClient` con `get_db` override-ado a una BD SQLite en memoria.
    """
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)

    session: Session = factory()
    seed_dev_data(session)
    session.close()

    def _override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _recommendations(client: TestClient) -> dict:
    """GET /recommendations/2025 -> body (assert 200)."""
    response = client.get("/api/v1/recommendations/2025")
    assert response.status_code == 200, response.text
    return response.json()


def _by_id(body: dict, rec_id: str) -> dict | None:
    """Devuelve la recomendación con ese id, o ``None``."""
    return next((r for r in body["recommendations"] if r["id"] == rec_id), None)


def test_recommendations_do_not_persist_journal_or_draft(client: TestClient) -> None:
    get_session = app.dependency_overrides[get_db]

    def snapshot() -> tuple[list[str], list[tuple[str, object]]]:
        generator = get_session()
        db = next(generator)
        try:
            entries = sorted(str(entry.id) for entry in db.scalars(select(JournalEntry)).all())
            drafts = sorted(
                (str(draft.id), draft.computed) for draft in db.scalars(select(FilingDraft)).all()
            )
            return entries, drafts
        finally:
            generator.close()

    before = snapshot()
    assert _recommendations(client)["year"] == 2025
    assert snapshot() == before
    assert client.post("/api/v1/filing/draft?year=2025").status_code == 200
    persisted = snapshot()
    assert persisted[0] and persisted[1]
    assert _recommendations(client)["year"] == 2025
    assert snapshot() == persisted
    assert _recommendations(client)["year"] == 2025
    assert snapshot() == persisted


def test_recommendation_error_rolls_back_temporary_projection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import recommendations

    assert client.post("/api/v1/filing/draft?year=2025").status_code == 200
    get_session = app.dependency_overrides[get_db]

    def snapshot() -> tuple[list[str], list[tuple[str, object]]]:
        generator = get_session()
        db = next(generator)
        try:
            entries = sorted(str(entry.id) for entry in db.scalars(select(JournalEntry)).all())
            drafts = sorted(
                (str(draft.id), draft.computed) for draft in db.scalars(select(FilingDraft)).all()
            )
            return entries, drafts
        finally:
            generator.close()

    before = snapshot()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated recommendation error")

    monkeypatch.setattr(recommendations, "build_recommendations", fail)
    with pytest.raises(RuntimeError, match="simulated recommendation error"):
        client.get("/api/v1/recommendations/2025")
    assert snapshot() == before


def test_owner_gets_elderly_dependent_recommendation(client: TestClient) -> None:
    """Rec 1: registrar a un familiar (老人扶養 別居) aparece con ahorro > 0."""
    body = _recommendations(client)
    rec = _by_id(body, "register_elderly_dependent")
    assert rec is not None, "falta la recomendación de 老人扶養"
    # Ahorro real (所得税 + 住民税) calculado por el escenario hipotético.
    assert rec["total_saving"] > 0
    assert rec["income_tax_saving"] > 0 or rec["resident_tax_saving"] > 0
    assert rec["priority"] == "alta"
    assert rec["action_route"] == "kosei-seikyu"


def test_owner_gets_housing_loan_recommendation(client: TestClient) -> None:
    """Rec 2: el 住宅ローン控除 rechazado aparece sin ahorro aplicado."""
    body = _recommendations(client)
    applied = _by_id(body, "housing_loan_applied")
    recover = _by_id(body, "recover_housing_loan")
    assert applied is None
    assert recover is not None, "falta la revisión del 住宅ローン控除"
    assert recover["status"] == "needs_info"
    assert recover["total_saving"] == 0


def test_owner_gets_loss_offset_confirmation(client: TestClient) -> None:
    """Rec 3: confirmación del 損益通算 (pérdida del 副業 compensa el 給与)."""
    body = _recommendations(client)
    rec = _by_id(body, "loss_offset_applied")
    assert rec is not None, "falta la confirmación del 損益通算"
    assert rec["category"] == "info"
    assert rec["status"] == "applied"
    assert "depende" in rec["body_es"]
    assert "vuelve parte" not in rec["body_es"]
    assert "還付されます" not in rec["body_jp"]


def test_furusato_does_not_claim_a_calculated_limit(client: TestClient) -> None:
    rec = _by_id(_recommendations(client), "furusato_nozei")
    if rec is not None:
        assert rec["total_saving"] == 0
        assert "límite depende" in rec["body_es"]


def test_recommendations_are_prioritized(client: TestClient) -> None:
    """Las recomendaciones vienen ordenadas por prioridad (alta -> baja)."""
    body = _recommendations(client)
    order = {"alta": 0, "media": 1, "baja": 2}
    priorities = [order[r["priority"]] for r in body["recommendations"]]
    assert priorities == sorted(priorities), priorities


def test_total_estimated_saving_sums_actionables(client: TestClient) -> None:
    """El ahorro total estimado suma SOLO las recomendaciones accionables."""
    body = _recommendations(client)
    actionable = [
        r for r in body["recommendations"] if r["status"] == "actionable"
    ]
    expected = sum(r["total_saving"] for r in actionable)
    assert body["total_estimated_saving"] == expected
    assert body["actionable_count"] == len(actionable)
    # El owner tiene al menos la recomendación de un familiar como accionable.
    assert body["actionable_count"] >= 1
    assert body["total_estimated_saving"] > 0


def test_every_recommendation_marked_as_estimate(client: TestClient) -> None:
    """Todas las recomendaciones llevan el flag 概算 (no somos 税理士)."""
    body = _recommendations(client)
    assert all(r["is_estimate"] for r in body["recommendations"])


def test_unsupported_year_returns_400(client: TestClient) -> None:
    """Un año sin parámetros fiscales devuelve 400."""
    response = client.get("/api/v1/recommendations/2099")
    assert response.status_code == 400, response.text
