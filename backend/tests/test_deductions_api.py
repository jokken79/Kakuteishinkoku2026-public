"""Tests del router del wizard de 控除 (Fase 3B-1).

Cubren el CRUD, la integracion con el calculo (agregar una 控除 baja el impuesto)
y la deteccion proactiva de sugerencias. Usan SQLite en memoria con un 年度 2025
sembrado, sin dependencias externas.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import app
from app.models import Base, FiscalYear, IncomeSource, Taxpayer, Transaction
from app.models.enums import IncomeType, TransactionSource, TransactionStatus


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Cliente de test con BD SQLite en memoria y un 年度 2025 abierto.

    Yields:
        `TestClient` con `get_db` override-ado.
    """
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)

    session: Session = factory()
    taxpayer = Taxpayer(name="テスト太郎")
    session.add(taxpayer)
    session.flush()
    fy = FiscalYear(
        taxpayer_id=taxpayer.id, year=2025, rules_ref="tax_rules/2025.json"
    )
    session.add(fy)
    session.flush()
    # 売上 del owner como IncomeSource (antes era hardcode ¥6,800,000): situa el
    # tramo marginal para que agregar 控除 baje el impuesto.
    session.add(
        IncomeSource(
            fiscal_year_id=fy.id,
            income_type=IncomeType.JIGYO,
            gross=6_800_000,
            withholding=0,
        )
    )
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


def _seed_transaction(client: TestClient, vendor: str, amount: int) -> None:
    """Inserta una transaccion OCR directa en la BD del cliente de test."""
    factory = app.dependency_overrides[get_db]
    gen = factory()
    db: Session = next(gen)
    try:
        fy = db.query(FiscalYear).first()
        db.add(
            Transaction(
                fiscal_year_id=fy.id,
                date=date(2025, 6, 1),
                vendor=vendor,
                total_amount=amount,
                source=TransactionSource.OCR,
                status=TransactionStatus.PENDING,
            )
        )
        db.commit()
    finally:
        gen.close()


def test_suggestion_uses_filing_type_confirmed_for_year(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import deductions

    assert client.put("/api/v1/fiscal-years/2025/filing-type", json={
        "value": "shiroiro", "backup_confirmed": True,
    }).status_code == 200
    _seed_transaction(client, "さとふる ふるさと納税", 50_000)
    seen: list[str] = []

    def capture(*_args: object, **kwargs: object) -> int:
        seen.append(str(kwargs["filing_type"]))
        return 0

    monkeypatch.setattr(deductions, "estimate_tax_saving", capture)
    assert client.get("/api/v1/deductions/suggestions?year=2025").status_code == 200
    assert seen == ["shiroiro"]


def test_list_deductions_empty(client: TestClient) -> None:
    """GET /deductions sin 控除 devuelve lista vacia + 基礎控除 en el total."""
    response = client.get("/api/v1/deductions", params={"year": 2025})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["year"] == 2025
    assert body["deductions"] == []
    # applied_total incluye el 基礎控除 (escalonado) aunque no haya filas.
    assert body["applied_total"] > 0


def test_create_and_list_deduction(client: TestClient) -> None:
    """POST /deductions crea una 控除 y aparece al listar."""
    create = client.post(
        "/api/v1/deductions",
        params={"year": 2025},
        json={"type": "shakai_hoken", "amount": 300_000},
    )
    assert create.status_code == 201, create.text
    created = create.json()
    assert created["type"] == "shakai_hoken"
    assert created["amount"] == 300_000

    listed = client.get("/api/v1/deductions", params={"year": 2025}).json()
    assert len(listed["deductions"]) == 1
    assert listed["deductions"][0]["id"] == created["id"]


def test_adding_deduction_lowers_tax(client: TestClient) -> None:
    """Agregar una 控除 (社会保険料 ¥300k) baja el impuesto del summary."""
    before = client.get("/api/v1/deductions/summary", params={"year": 2025}).json()
    tax_before = before["tax_with_deductions"]

    client.post(
        "/api/v1/deductions",
        params={"year": 2025},
        json={"type": "shakai_hoken", "amount": 300_000},
    )

    after = client.get("/api/v1/deductions/summary", params={"year": 2025}).json()
    tax_after = after["tax_with_deductions"]

    assert tax_after < tax_before, f"{tax_after} should be < {tax_before}"
    assert after["total_saving"] > 0
    # El total aplicado debe subir en ~¥300k (sin tope para 社会保険料).
    assert after["applied_total"] - before["applied_total"] == 300_000


def test_patch_deduction_changes_amount_and_tax(client: TestClient) -> None:
    """PATCH del monto de una 控除 cambia el impuesto calculado."""
    created = client.post(
        "/api/v1/deductions",
        params={"year": 2025},
        json={"type": "ideco", "amount": 100_000},
    ).json()

    tax_small = client.get(
        "/api/v1/deductions/summary", params={"year": 2025}
    ).json()["tax_with_deductions"]

    patch = client.patch(
        f"/api/v1/deductions/{created['id']}", json={"amount": 276_000}
    )
    assert patch.status_code == 200
    assert patch.json()["amount"] == 276_000

    tax_big = client.get(
        "/api/v1/deductions/summary", params={"year": 2025}
    ).json()["tax_with_deductions"]
    assert tax_big < tax_small


def test_delete_deduction(client: TestClient) -> None:
    """DELETE /deductions/{id} elimina la 控除."""
    created = client.post(
        "/api/v1/deductions",
        params={"year": 2025},
        json={"type": "seimei_hoken", "amount": 80_000},
    ).json()

    delete = client.delete(f"/api/v1/deductions/{created['id']}")
    assert delete.status_code == 204

    listed = client.get("/api/v1/deductions", params={"year": 2025}).json()
    assert listed["deductions"] == []


def test_suggestions_returns_common_reminders(client: TestClient) -> None:
    """GET /deductions/suggestions devuelve recordatorios comunes sin datos."""
    response = client.get("/api/v1/deductions/suggestions", params={"year": 2025})
    assert response.status_code == 200, response.text
    body = response.json()
    types = {s["type"] for s in body}
    # Los 3 recordatorios que casi todos tienen.
    assert {"shakai_hoken", "ideco", "seimei_hoken"} <= types
    # Sin importes reales no se presenta un ahorro basado en pagos supuestos.
    for s in body:
        if s["type"] in {"shakai_hoken", "ideco", "seimei_hoken"}:
            assert s["estimated_saving"] is None


def test_suggestions_detects_medical_from_transactions(client: TestClient) -> None:
    """Una transaccion de farmacia genera la sugerencia de 医療費控除."""
    _seed_transaction(client, "○○薬局 渋谷店", 150_000)
    body = client.get(
        "/api/v1/deductions/suggestions", params={"year": 2025}
    ).json()
    medical = [s for s in body if s["type"] == "iryohi"]
    assert len(medical) == 1
    assert "医療" in medical[0]["label"] or "医療" in medical[0]["reason"]


def test_suggestions_detects_furusato(client: TestClient) -> None:
    """Una transaccion de ふるさと納税 genera el recordatorio de declararla."""
    _seed_transaction(client, "さとふる ふるさと納税", 50_000)
    body = client.get(
        "/api/v1/deductions/suggestions", params={"year": 2025}
    ).json()
    furusato = [s for s in body if s["type"] == "furusato"]
    assert len(furusato) == 1
    assert "ワンストップ" in furusato[0]["reason"]


def test_suggestion_skips_already_registered(client: TestClient) -> None:
    """Si el 社会保険料控除 ya esta registrado, no se vuelve a sugerir."""
    client.post(
        "/api/v1/deductions",
        params={"year": 2025},
        json={"type": "shakai_hoken", "amount": 300_000},
    )
    body = client.get(
        "/api/v1/deductions/suggestions", params={"year": 2025}
    ).json()
    assert all(s["type"] != "shakai_hoken" for s in body)


def test_unsupported_year_returns_404(client: TestClient) -> None:
    """Un anio sin 年度 sembrado devuelve 404 al listar."""
    response = client.get("/api/v1/deductions", params={"year": 2099})
    assert response.status_code == 404
