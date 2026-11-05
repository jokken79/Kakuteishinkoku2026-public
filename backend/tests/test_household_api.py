"""Tests del módulo 家計簿 (libro de gastos personales, NO fiscal).

Cubren:
    - CRUD: crear / listar (por mes) / editar / borrar un gasto personal.
    - Summary: total del mes + desglose por 費目.
    - Filtro por mes: gastos de otros meses no se cuentan.
    - Puente 事業→家計: mover un ítem del 仕訳トレイ al 家計簿 lo crea como
      gasto personal y marca la transacción como ``rejected`` (la saca del flujo
      del negocio, NO entra a la declaración).

Usan SQLite en memoria (no ensucian el repo ni la lógica fiscal).
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import app
from app.models import (
    Base,
    FiscalYear,
    FiscalYearStatus,
    Taxpayer,
    Transaction,
    TransactionSource,
    TransactionStatus,
)


@pytest.fixture
def factory_engine() -> Generator[tuple[Engine, object], None, None]:
    """Engine SQLite en memoria + fabrica de sesiones con un Taxpayer base."""
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    try:
        yield engine, factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(factory_engine) -> Generator[TestClient, None, None]:
    """Cliente con BD SQLite en memoria."""
    _engine, factory = factory_engine

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


def _create(
    client: TestClient,
    *,
    date: str,
    amount: int,
    category: str = "shokuhi",
    memo: str | None = None,
) -> dict:
    """Crea un gasto personal y devuelve el body."""
    payload = {"date": date, "amount": amount, "category": category}
    if memo is not None:
        payload["memo"] = memo
    resp = client.post("/api/v1/household", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- Alta + listado --------------------------------------------------------


def test_create_and_list(client: TestClient) -> None:
    """Crear un gasto y listarlo por mes."""
    created = _create(client, date="2026-06-10", amount=1200, memo="スーパー")
    assert created["amount"] == 1200
    assert created["category"] == "shokuhi"
    assert created["memo"] == "スーパー"

    listed = client.get("/api/v1/household", params={"year": 2026, "month": 6})
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["id"] == created["id"]


def test_list_filters_by_month(client: TestClient) -> None:
    """Los gastos de otros meses no aparecen en el listado del mes."""
    _create(client, date="2026-06-05", amount=1000)
    _create(client, date="2026-07-05", amount=2000)

    june = client.get("/api/v1/household", params={"year": 2026, "month": 6}).json()
    assert [e["amount"] for e in june] == [1000]

    july = client.get("/api/v1/household", params={"year": 2026, "month": 7}).json()
    assert [e["amount"] for e in july] == [2000]


def test_create_rejects_non_positive_amount(client: TestClient) -> None:
    """Un monto <= 0 es rechazado por validación (422)."""
    resp = client.post(
        "/api/v1/household",
        json={"date": "2026-06-10", "amount": 0, "category": "shokuhi"},
    )
    assert resp.status_code == 422


def test_create_rejects_unknown_category(client: TestClient) -> None:
    """Una categoría 費目 inexistente es rechazada (422)."""
    resp = client.post(
        "/api/v1/household",
        json={"date": "2026-06-10", "amount": 500, "category": "no_existe"},
    )
    assert resp.status_code == 422


# --- Summary ---------------------------------------------------------------


def test_summary_totals_by_category(client: TestClient) -> None:
    """El summary agrega total general y por 費目 del mes."""
    _create(client, date="2026-06-01", amount=1000, category="shokuhi")
    _create(client, date="2026-06-15", amount=2000, category="shokuhi")
    _create(client, date="2026-06-20", amount=500, category="kotsuhi")
    # Otro mes: no debe contar.
    _create(client, date="2026-05-20", amount=9999, category="shokuhi")

    resp = client.get(
        "/api/v1/household/summary", params={"year": 2026, "month": 6}
    )
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["year"] == 2026
    assert summary["month"] == 6
    assert summary["total"] == 3500  # 1000+2000+500, sin el de mayo

    by_cat = {c["category"]: c for c in summary["by_category"]}
    assert by_cat["shokuhi"]["total"] == 3000
    assert by_cat["shokuhi"]["count"] == 2
    assert by_cat["kotsuhi"]["total"] == 500
    # Orden: 食費 (3000) antes que 交通費 (500), por monto descendente.
    assert summary["by_category"][0]["category"] == "shokuhi"


def test_summary_empty_month(client: TestClient) -> None:
    """Un mes sin gastos devuelve total 0 y desglose vacío (sin NaN)."""
    resp = client.get(
        "/api/v1/household/summary", params={"year": 2026, "month": 6}
    )
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["total"] == 0
    assert summary["by_category"] == []


# --- Edición + borrado -----------------------------------------------------


def test_patch_updates_fields(client: TestClient) -> None:
    """PATCH actualiza solo los campos provistos."""
    created = _create(client, date="2026-06-10", amount=1200, category="shokuhi")
    resp = client.patch(
        f"/api/v1/household/{created['id']}",
        json={"amount": 1500, "category": "gorakuhi"},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["amount"] == 1500
    assert updated["category"] == "gorakuhi"
    # date no cambió.
    assert updated["date"] == "2026-06-10"


def test_patch_not_found_404(client: TestClient) -> None:
    """PATCH de un id inexistente devuelve 404."""
    resp = client.patch(
        "/api/v1/household/00000000-0000-0000-0000-000000000000",
        json={"amount": 100},
    )
    assert resp.status_code == 404


def test_delete_removes_expense(client: TestClient) -> None:
    """DELETE elimina el gasto y desaparece del listado."""
    created = _create(client, date="2026-06-10", amount=1200)
    delete = client.delete(f"/api/v1/household/{created['id']}")
    assert delete.status_code == 204
    listed = client.get(
        "/api/v1/household", params={"year": 2026, "month": 6}
    ).json()
    assert listed == []


# --- Puente 事業 → 家計 (Parte 3) ------------------------------------------


def _seed_pending_transaction(factory) -> str:
    """Crea un Taxpayer + FiscalYear + Transaction pendiente y devuelve su id."""
    db: Session = factory()
    taxpayer = Taxpayer(name="個人 太郎")
    db.add(taxpayer)
    db.flush()
    fy = FiscalYear(
        taxpayer_id=taxpayer.id,
        year=2026,
        rules_ref="2026",
        status=FiscalYearStatus.OPEN,
    )
    db.add(fy)
    db.flush()
    tx = Transaction(
        fiscal_year_id=fy.id,
        date=__import__("datetime").date(2026, 6, 12),
        vendor="ドラッグストア",
        total_amount=3300,
        source=TransactionSource.OCR,
        status=TransactionStatus.PENDING,
    )
    db.add(tx)
    db.commit()
    tx_id = str(tx.id)
    db.close()
    return tx_id


def test_from_transaction_moves_to_household(
    client: TestClient, factory_engine
) -> None:
    """Mover un ítem del 仕訳トレイ al 家計簿 lo crea como gasto personal.

    Además marca la transacción como ``rejected`` para sacarla del flujo del
    negocio (no entra al 仕訳 ni a la declaración).
    """
    _engine, factory = factory_engine
    tx_id = _seed_pending_transaction(factory)

    resp = client.post(
        f"/api/v1/household/from-transaction/{tx_id}",
        json={"category": "nichiyohin"},
    )
    assert resp.status_code == 201, resp.text
    expense = resp.json()
    assert expense["amount"] == 3300
    assert expense["category"] == "nichiyohin"
    assert expense["memo"] == "ドラッグストア"  # vendor -> memo
    assert expense["date"] == "2026-06-12"

    # El gasto aparece en el 家計簿 del mes.
    listed = client.get(
        "/api/v1/household", params={"year": 2026, "month": 6}
    ).json()
    assert len(listed) == 1

    # La transacción quedó rechazada (fuera del flujo del negocio).
    db: Session = factory()
    import uuid as _uuid

    tx = db.get(Transaction, _uuid.UUID(tx_id))
    assert tx is not None
    assert tx.status == TransactionStatus.REJECTED
    db.close()


def test_from_transaction_not_found_404(client: TestClient) -> None:
    """Mover una transacción inexistente devuelve 404."""
    resp = client.post(
        "/api/v1/household/from-transaction/00000000-0000-0000-0000-000000000000",
        json={"category": "sonota"},
    )
    assert resp.status_code == 404
