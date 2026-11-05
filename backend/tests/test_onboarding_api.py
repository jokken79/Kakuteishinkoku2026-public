"""Tests del router de onboarding (`app.api.onboarding`).

Cubren:
    - `GET /onboarding/status`: refleja `onboarded` del Taxpayer y la presencia
      de ingresos; sin Taxpayer => onboarded=false / has_taxpayer=false.
    - `POST /onboarding/complete`: crea/actualiza el perfil, asegura el 年度,
      persiste las `IncomeSource` iniciales y marca `onboarded=True`.

Usan SQLite en memoria. Algunos tests parten de una BD VACÍA (usuario nuevo) y
otros del seed (demo ya onboardeado).
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
from app.models.entities import FiscalYear, IncomeSource, Taxpayer
from app.seed.dev_seed import seed_demo_data


def _make_client(*, seeded: bool) -> tuple[TestClient, Engine, object]:
    """Crea un cliente sobre SQLite en memoria, con o sin seed.

    Args:
        seeded: Si ``True`` siembra el demo (owner 免税, onboarded=True).

    Returns:
        Tupla ``(client, engine, factory)`` para inspección/limpieza.
    """
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)

    if seeded:
        session: Session = factory()
        seed_demo_data(session)
        session.close()

    def _override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app), engine, factory


@pytest.fixture
def fresh_client() -> Generator[tuple[TestClient, object], None, None]:
    """Cliente sobre BD VACÍA (simula un usuario nuevo, sin Taxpayer)."""
    client, engine, factory = _make_client(seeded=False)
    try:
        yield client, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def seeded_client() -> Generator[tuple[TestClient, object], None, None]:
    """Cliente sobre el seed (demo onboardeado, owner 免税)."""
    client, engine, factory = _make_client(seeded=True)
    try:
        yield client, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_status_empty_db_is_not_onboarded(
    fresh_client: tuple[TestClient, object],
) -> None:
    """Sin Taxpayer => onboarded=false, has_taxpayer=false, has_income=false."""
    client, _ = fresh_client
    res = client.get("/api/v1/onboarding/status")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == {
        "onboarded": False,
        "has_taxpayer": False,
        "has_income": False,
    }


def test_status_seed_demo_is_onboarded(
    seeded_client: tuple[TestClient, object],
) -> None:
    """El demo del seed está marcado onboarded=true (no muestra onboarding)."""
    client, _ = seeded_client
    res = client.get("/api/v1/onboarding/status")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["onboarded"] is True
    assert body["has_taxpayer"] is True
    # El seed carga 売上 6.8M + 源泉 410k => has_income True.
    assert body["has_income"] is True


def test_complete_creates_profile_income_and_marks_onboarded(
    fresh_client: tuple[TestClient, object],
) -> None:
    """`complete` crea Taxpayer + 年度 + IncomeSource y marca onboarded=True."""
    client, factory = fresh_client
    payload = {
        "name": "山田 太郎",
        "name_kana": "ヤマダ タロウ",
        "postal_code": "100-0001",
        "address": "東京都千代田区1-1",
        "birth_date": "1990-04-01",
        "business_type": "デザイナー",
        "filing_type": "aoiro_65",
        "is_taxable_consumption": False,
        "filing_office": "tsushima",
        "incomes": [
            {"income_type": "jigyo", "gross": 5_000_000, "withholding": 0},
            {"income_type": "kyuyo", "gross": 0, "withholding": 120_000},
        ],
    }
    res = client.post("/api/v1/onboarding/complete", json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["onboarded"] is True
    assert body["year"] == 2025
    assert body["income_count"] == 2

    # Verifica persistencia real en la BD.
    db: Session = factory()
    try:
        taxpayer = db.scalars(select(Taxpayer)).one()
        assert taxpayer.onboarded is True
        assert taxpayer.name == "山田 太郎"
        # SQLite devuelve el enum como str crudo: comparar por value.
        assert getattr(taxpayer.filing_type, "value", taxpayer.filing_type) == "aoiro_65"
        assert taxpayer.filing_office == "tsushima"

        fy = db.scalars(select(FiscalYear)).one()
        assert fy.year == 2025

        sources = db.scalars(select(IncomeSource)).all()
        kinds = {
            getattr(s.income_type, "value", s.income_type): s for s in sources
        }
        assert kinds["jigyo"].gross == 5_000_000
        assert kinds["kyuyo"].withholding == 120_000
    finally:
        db.close()

    # El status ahora refleja onboarded.
    status_res = client.get("/api/v1/onboarding/status")
    assert status_res.json()["onboarded"] is True
    assert status_res.json()["has_income"] is True


def test_complete_is_idempotent_on_income(
    fresh_client: tuple[TestClient, object],
) -> None:
    """Reenviar `complete` actualiza (no duplica) la IncomeSource del tipo."""
    client, factory = fresh_client
    first = {
        "name": "鈴木 花子",
        "filing_type": "shiroiro",
        "incomes": [{"income_type": "jigyo", "gross": 3_000_000}],
    }
    assert client.post("/api/v1/onboarding/complete", json=first).status_code == 200

    second = {
        "name": "鈴木 花子",
        "filing_type": "shiroiro",
        "incomes": [{"income_type": "jigyo", "gross": 4_200_000}],
    }
    assert client.post("/api/v1/onboarding/complete", json=second).status_code == 200

    db: Session = factory()
    try:
        sources = db.scalars(select(IncomeSource)).all()
        # Una sola fila jigyo, con el monto actualizado.
        jigyo = [
            s
            for s in sources
            if getattr(s.income_type, "value", s.income_type) == "jigyo"
        ]
        assert len(jigyo) == 1
        assert jigyo[0].gross == 4_200_000
        # Un solo 年度 (no se duplicó).
        assert len(db.scalars(select(FiscalYear)).all()) == 1
    finally:
        db.close()


def test_onboarding_filing_type_and_income_stay_in_selected_year(
    fresh_client: tuple[TestClient, object],
) -> None:
    client, _factory = fresh_client
    assert client.post("/api/v1/onboarding/complete?year=2025", json={
        "name": "Test", "filing_type": "aoiro_65",
        "incomes": [{"income_type": "jigyo", "gross": 100_000}],
    }).status_code == 200
    result = client.post("/api/v1/onboarding/complete?year=2026", json={
        "filing_type": "shiroiro",
        "incomes": [{"income_type": "jigyo", "gross": 200_000}],
    })
    assert result.status_code == 200
    assert result.json()["year"] == 2026
    assert client.get("/api/v1/fiscal-years/2025/filing-type").json() == {
        "value": "aoiro_65", "source": "year",
    }
    assert client.get("/api/v1/fiscal-years/2026/filing-type").json() == {
        "value": "shiroiro", "source": "year",
    }
    db: Session = _factory()
    try:
        years = {fy.year: fy for fy in db.scalars(select(FiscalYear)).all()}
        assert years[2025].income_sources[0].gross == 100_000
        assert years[2026].income_sources[0].gross == 200_000
        assert db.scalars(select(Taxpayer)).one().filing_type == "aoiro_65"
    finally:
        db.close()


def test_onboarding_refuses_ambiguous_income_without_changing_profile(
    fresh_client: tuple[TestClient, object],
) -> None:
    client, factory = fresh_client
    assert client.post("/api/v1/onboarding/complete?year=2026", json={
        "name": "Original", "filing_type": "aoiro_65",
        "incomes": [{"income_type": "kyuyo", "gross": 100_000}],
    }).status_code == 200
    db: Session = factory()
    try:
        fy = db.scalars(select(FiscalYear)).one()
        db.add(IncomeSource(fiscal_year_id=fy.id, income_type="kyuyo", gross=200_000))
        db.commit()
    finally:
        db.close()
    result = client.post("/api/v1/onboarding/complete?year=2026", json={
        "name": "Changed", "filing_type": "shiroiro",
        "incomes": [{"income_type": "kyuyo", "gross": 999_999}],
    })
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "onboarding_income_ambiguous"
    db = factory()
    try:
        assert db.scalars(select(Taxpayer)).one().name == "Original"
        assert db.scalars(select(FiscalYear)).one().filing_type_override == "aoiro_65"
        amounts = sorted(row.gross for row in db.scalars(select(IncomeSource)).all())
        assert amounts == [100_000, 200_000]
    finally:
        db.close()


def test_onboarding_preserves_omitted_income_fields_and_accepts_explicit_zero(
    fresh_client: tuple[TestClient, object],
) -> None:
    client, factory = fresh_client
    assert client.post("/api/v1/onboarding/complete?year=2026", json={
        "name": "Test", "incomes": [{
            "income_type": "kyuyo", "gross": 5_000_000, "withholding": 100_000,
        }],
    }).status_code == 200
    assert client.post("/api/v1/onboarding/complete?year=2026", json={
        "incomes": [{"income_type": "kyuyo", "withholding": 0}],
    }).status_code == 200
    db: Session = factory()
    try:
        source = db.scalars(select(IncomeSource)).one()
        assert source.gross == 5_000_000
        assert source.withholding == 0
    finally:
        db.close()


def test_complete_updates_existing_demo_taxpayer(
    seeded_client: tuple[TestClient, object],
) -> None:
    """Sobre el seed, `complete` actualiza el Taxpayer existente (single-user)."""
    client, factory = seeded_client
    res = client.post(
        "/api/v1/onboarding/complete",
        json={"business_type": "コンサルタント", "is_taxable_consumption": True},
    )
    assert res.status_code == 200, res.text

    db: Session = factory()
    try:
        # Sigue habiendo UN solo taxpayer (no se creó uno nuevo).
        taxpayer = db.scalars(select(Taxpayer)).one()
        assert taxpayer.business_type == "コンサルタント"
        assert taxpayer.is_taxable_consumption is True
        assert taxpayer.onboarded is True
    finally:
        db.close()
