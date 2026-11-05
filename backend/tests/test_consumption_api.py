"""Tests del router de 消費税 (`app.api.consumption`).

Cubren:
    - `GET /consumption/calculate`: 課税事業者 -> 3 opciones + recomendacion;
      免税事業者 -> respuesta clara (is_taxable=false).
    - `GET /consumption/{year}/pdf`: PDF para 課税; 400 para 免税.
    - `GET/PATCH /taxpayer`: config del 消費税 (課税事業者 + metodo + 事業区分).

Usan SQLite en memoria con el seed (owner 免税 por defecto).
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import app
from app.models import Base, Transaction
from app.models.enums import TransactionStatus
from app.seed.dev_seed import seed_demo_data


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Cliente de test con el seed (owner 免税) y los 取引 confirmados."""
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


def _enable_taxable(client: TestClient, *, method: str, category: int | None = None):
    """Marca al contribuyente como 課税事業者 con el metodo/区分 indicados."""
    payload: dict = {"is_taxable_consumption": True, "consumption_method": method}
    if category is not None:
        payload["consumption_business_category"] = category
    res = client.patch("/api/v1/taxpayer", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def test_calculate_menzei_by_default(client: TestClient) -> None:
    """El owner del seed es 免税: /calculate devuelve is_taxable=false sin recomendacion."""
    res = client.get("/api/v1/consumption/calculate?year=2025")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["is_taxable"] is False
    assert data["recommended"] is None
    assert data["recommended_saving"] == 0


def test_calculate_for_year_guards_missing_consumption_rules() -> None:
    """Si el `TaxRules` del año no trae bloque de 消費税, falla con error CLARO.

    Hardening: `calculate_consumption_for_year` no debe explotar con un
    `AttributeError` opaco si `rules.consumption` es None; debe lanzar un
    `ValueError` accionable que apunte al JSON/parámetros del año.
    """
    from app.domain.tax.consumption import calculate_consumption_for_year
    from app.services.tax_rules import load_tax_rules

    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        seed_demo_data(session)
        session.commit()
        # Año fiscal válido y sembrado, pero reglas SIN bloque de 消費税.
        broken_rules = load_tax_rules(2025).model_copy(update={"consumption": None})
        with pytest.raises(ValueError, match="消費税"):
            calculate_consumption_for_year(session, 2025, rules=broken_rules)
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_pdf_blocked_for_menzei(client: TestClient) -> None:
    """免税事業者: /pdf devuelve 400 con codigo claro (申告不要)."""
    res = client.get("/api/v1/consumption/2025/pdf")
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "menzei_jigyosha"


def test_calculate_taxable_returns_three_options(client: TestClient) -> None:
    """課税事業者: /calculate devuelve 本則 / 簡易 / 2割特例 + recomendacion.

    El seed tiene 売上 ¥6,800,000 -> 売上税額(国税) = 6,800,000 × 7.8/110 = 482,181.
    Con 事業区分 5 (サービス, 50%) y pocos gastos適格, el 2割特例 (paga 20%) es el
    mas barato -> recomendado.
    """
    _enable_taxable(client, method="tokurei_2wari", category=5)
    res = client.get("/api/v1/consumption/calculate?year=2025")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["is_taxable"] is True
    # 売上税額(国税): 6,800,000 × 7.8/110 = 482,181 (truncado).
    assert data["sales_breakdown"]["national_tax_total"] == int(6_800_000 * 7.8 / 110)
    # Las 3 opciones presentes.
    assert {data["honsoku"]["method"], data["kani"]["method"], data["tokurei"]["method"]} == {
        "honsoku",
        "kani",
        "tokurei",
    }
    assert all(
        data[method]["eligibility_status"] == "unverified"
        for method in ("honsoku", "kani", "tokurei")
    )
    assert all(not data[method]["eligible"] for method in ("honsoku", "kani", "tokurei"))
    assert data["recommended"] is None


def test_pdf_generated_for_taxable(client: TestClient) -> None:
    """El PDF identifica el resultado como simulación, no declaración oficial."""
    import pymupdf

    _enable_taxable(client, method="tokurei_2wari", category=5)
    res = client.get("/api/v1/consumption/2025/pdf")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content[:4] == b"%PDF"
    assert len(res.content) > 1000
    with pymupdf.open(stream=res.content, filetype="pdf") as document:
        content = "".join(page.get_text() for page in document)
    assert "提出用ではありません" in content
    assert "要件未確認" in content
    assert "登録番号は形式のみ確認" in content
    assert "税率不明" in content


def test_taxpayer_get_and_patch_roundtrip(client: TestClient) -> None:
    """GET /taxpayer refleja la config; PATCH la actualiza (課税 + metodo + 区分)."""
    initial = client.get("/api/v1/taxpayer")
    assert initial.status_code == 200, initial.text
    assert initial.json()["is_taxable_consumption"] is False

    updated = _enable_taxable(client, method="kani", category=3)
    assert updated["is_taxable_consumption"] is True
    assert updated["consumption_method"] == "kani"
    assert updated["consumption_business_category"] == 3
    # El catalogo de etiquetas viene para la UI.
    assert "1" in {str(k) for k in updated["business_category_labels"]}

    # Persistido: una nueva lectura mantiene el cambio.
    again = client.get("/api/v1/taxpayer")
    assert again.json()["consumption_method"] == "kani"


def test_patch_rejects_invalid_category(client: TestClient) -> None:
    """事業区分 fuera de 1〜6 -> 422 (validacion Pydantic)."""
    res = client.patch(
        "/api/v1/taxpayer",
        json={"is_taxable_consumption": True, "consumption_business_category": 9},
    )
    assert res.status_code == 422


def test_kani_method_changes_recommendation(client: TestClient) -> None:
    """El 事業区分 1 (卸売 90%) reduce mucho el 簡易, pudiendo ganarle al 特例.

    第1種 90%: 簡易控除 = 売上税額 × 0.9, deja solo 10% -> mas barato que 2割 (20%).
    """
    _enable_taxable(client, method="kani", category=1)
    res = client.get("/api/v1/consumption/calculate?year=2025")
    data = res.json()
    assert data["kani"]["eligibility_status"] == "unverified"
    assert data["kani"]["total_tax"] < data["tokurei"]["total_tax"]
    assert data["recommended"] is None
