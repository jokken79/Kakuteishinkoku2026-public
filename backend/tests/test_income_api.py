"""Tests del modulo de 収入 (IncomeSource) — ingresos editables del owner.

Cubren:
    - El CRUD de IncomeSource (list/create/patch/delete + validacion de tipo).
    - Que el draft lea el 売上 de IncomeSource (no el hardcode): editar el 売上
      cambia el 事業所得 y el 納付額; el 源泉 viene de IncomeSource.
    - Que sin IncomeSource el 売上 sea 0 (no el hardcode ¥6,800,000).

Usan SQLite en memoria con el escenario de seed (que ahora incluye IncomeSource),
sin dependencias externas.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import app
from app.models import Base, FiscalYear, Taxpayer, Transaction
from app.models.enums import TransactionStatus
from app.seed.dev_seed import seed_demo_data


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Cliente de test con el seed (taxpayer + 年度 + IncomeSource) confirmado.

    Yields:
        `TestClient` con `get_db` override-ado a SQLite en memoria.
    """
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)

    session: Session = factory()
    seed_demo_data(session)
    for tx in session.query(Transaction).all():
        tx.status = TransactionStatus.CONFIRMED
    session.commit()
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


@pytest.fixture
def empty_client() -> Generator[TestClient, None, None]:
    """Cliente con un 年度 2025 SIN ninguna IncomeSource (para defaults a 0)."""
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)

    session: Session = factory()
    from app.seed.accounts import seed_accounts

    seed_accounts(session, commit=False)
    tp = Taxpayer(name="空 太郎")
    session.add(tp)
    session.flush()
    session.add(FiscalYear(taxpayer_id=tp.id, year=2025, rules_ref="2025"))
    session.commit()
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


# --- CRUD -----------------------------------------------------------------


def test_seed_loads_income_sources(client: TestClient) -> None:
    """El seed carga el 売上 (6.8M) y el 源泉 (410k) como IncomeSource editables."""
    resp = client.get("/api/v1/income-sources", params={"year": 2025})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sales_revenue"] == 6_800_000
    assert body["total_withholding"] == 410_000
    types = {s["income_type"] for s in body["income_sources"]}
    assert {"jigyo", "kyuyo"} <= types


def test_create_income_source(client: TestClient) -> None:
    """POST /income-sources crea una fuente y aparece al listar."""
    create = client.post(
        "/api/v1/income-sources",
        params={"year": 2025},
        json={"income_type": "zatsu", "gross": 200_000, "expenses": 50_000},
    )
    assert create.status_code == 201, create.text
    created = create.json()
    assert created["income_type"] == "zatsu"
    assert created["gross"] == 200_000
    assert created["expenses"] == 50_000


def test_patch_income_label_preserves_other_metadata(client: TestClient) -> None:
    created = client.post(
        "/api/v1/income-sources", params={"year": 2025},
        json={"income_type": "zatsu", "gross": 100_000, "expenses": 12_000,
              "meta": {"label": "Cliente A", "reference": "original"}},
    ).json()
    updated = client.patch(
        f"/api/v1/income-sources/{created['id']}",
        json={"meta": {"label": "Cliente B"}},
    )
    assert updated.status_code == 200
    assert updated.json()["meta"]["label"] == "Cliente B"
    assert updated.json()["meta"]["reference"] == "original"
    assert updated.json()["expenses"] == 12_000


def test_filing_combines_two_salaries_and_preserves_withholding(client: TestClient) -> None:
    from app.domain.tax.income import salary_income
    from app.services.tax_rules import load_tax_rules

    existing = client.get("/api/v1/income-sources", params={"year": 2025}).json()
    old_salary = sum(
        item["gross"] for item in existing["income_sources"] if item["income_type"] == "kyuyo"
    )
    response = client.post(
        "/api/v1/income-sources", params={"year": 2025},
        json={"income_type": "kyuyo", "gross": 2_000_000, "withholding": 100_000},
    )
    assert response.status_code == 201, response.text
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    salaries = [item for item in draft["income_breakdown"] if item["kind"] == "kyuyo"]
    assert len(salaries) == 1
    assert salaries[0]["amount"] == salary_income(old_salary + 2_000_000, load_tax_rules(2025))
    assert draft["withholding_total"] == existing["total_withholding"] + 100_000
    from xml.etree import ElementTree as ET

    xtx = client.get(f"/api/v1/filing/{draft['draft_id']}/xtx")
    assert xtx.status_code == 200
    assert ET.fromstring(xtx.content).findtext(".//ABB00080") == str(old_salary + 2_000_000)
    import pymupdf

    pdf = client.get(f"/api/v1/filing/{draft['draft_id']}/pdf?form=shinkokusho")
    assert pdf.status_code == 200
    with pymupdf.open(stream=pdf.content, filetype="pdf") as document:
        assert str(old_salary + 2_000_000) in document[0].get_text().replace(" ", "")


def test_create_unsupported_type_400(client: TestClient) -> None:
    """Un tipo fuera del MVP (ej. taishoku) devuelve 400."""
    resp = client.post(
        "/api/v1/income-sources",
        params={"year": 2025},
        json={"income_type": "taishoku", "gross": 100_000},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_income_type"


def test_delete_income_source(client: TestClient) -> None:
    """DELETE /income-sources/{id} elimina la fuente."""
    created = client.post(
        "/api/v1/income-sources",
        params={"year": 2025},
        json={"income_type": "fudosan", "gross": 300_000},
    ).json()
    delete = client.delete(f"/api/v1/income-sources/{created['id']}")
    assert delete.status_code == 204
    listed = client.get("/api/v1/income-sources", params={"year": 2025}).json()
    assert all(s["id"] != created["id"] for s in listed["income_sources"])


def test_no_fiscal_year_404(client: TestClient) -> None:
    """Un anio sin 年度 sembrado devuelve 404 al listar."""
    resp = client.get("/api/v1/income-sources", params={"year": 2099})
    assert resp.status_code == 404


# --- Integracion con el draft (hardcode removido) -------------------------


def _jigyo_id(client: TestClient) -> str:
    """Devuelve el id de la fila jigyo (売上) del seed."""
    body = client.get("/api/v1/income-sources", params={"year": 2025}).json()
    jigyo = next(s for s in body["income_sources"] if s["income_type"] == "jigyo")
    return jigyo["id"]


def test_editing_sales_changes_business_income_and_payment(client: TestClient) -> None:
    """Editar el 売上 cambia el 事業所得 y el 納付額 del draft (no hardcode)."""
    before = client.post("/api/v1/filing/draft?year=2025").json()
    assert before["sales_revenue"] == 6_800_000

    # Subir el 売上 a ¥8,000,000.
    client.patch(
        f"/api/v1/income-sources/{_jigyo_id(client)}", json={"gross": 8_000_000}
    )
    after = client.post("/api/v1/filing/draft?year=2025").json()

    assert after["sales_revenue"] == 8_000_000
    # +¥1,200,000 de 売上 => sube el 事業所得 y el 納付額.
    assert after["business_income"] > before["business_income"]
    assert after["final_amount"] > before["final_amount"]


def test_withholding_comes_from_income_source(client: TestClient) -> None:
    """El 源泉徴収 del draft = Σ withholding de IncomeSource (no el ¥410k fijo)."""
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    assert draft["withholding_total"] == 410_000

    # Subir el 源泉 del 給与 a ¥600,000.
    body = client.get("/api/v1/income-sources", params={"year": 2025}).json()
    kyuyo = next(s for s in body["income_sources"] if s["income_type"] == "kyuyo")
    client.patch(
        f"/api/v1/income-sources/{kyuyo['id']}", json={"withholding": 600_000}
    )

    after = client.post("/api/v1/filing/draft?year=2025").json()
    assert after["withholding_total"] == 600_000
    # Mas 源泉 retenido => menor 納付額 (mas pagado a cuenta).
    assert after["final_amount"] < draft["final_amount"]


def test_no_income_source_defaults_to_zero(empty_client: TestClient) -> None:
    """Sin IncomeSource el 売上 y el 源泉 son 0 (no el hardcode 6.8M / 410k)."""
    draft = empty_client.post("/api/v1/filing/draft?year=2025").json()
    assert draft["sales_revenue"] == 0
    assert draft["withholding_total"] == 0
    assert draft["business_income"] == 0


def test_demo_payment_unchanged(client: TestClient) -> None:
    """El demo (個人事業主 免税) da el 納付額 redondeado de ¥95,200.

    Escenario seed: 売上 ¥6,800,000, 経費 ¥331,498 (12 仕訳 confirmados), 青色65万,
    控除 社会保険 ¥300,000 + iDeCo ¥276,000 + 基礎 ¥630,000 = ¥1,206,000, 源泉 ¥410,000.
    El saldo positivo se redondea a centenas de yenes.
    """
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    assert draft["final_amount"] == 95_200
