"""Tests del router de 年度 (`app.api.fiscal_years`) y del service.

Cubren:
    - `GET /fiscal-years`: lista los 年度 (year + status) ordenados desc y expone
      el año activo (OPEN más reciente). Sin Taxpayer => vacío.
    - `POST /fiscal-years`: crea un 年度 nuevo (idempotente) y lo devuelve.
    - `PATCH /fiscal-years/{year}`: cambia el status (open/closed/filed); 404 si
      no existe.
    - El service `resolve_active_fiscal_year` prefiere el OPEN más reciente.
    - Los saldos de apertura quedan aislados por 年度 y bloqueados al cerrar.

Usan SQLite en memoria. Algunos tests parten de una BD VACÍA (usuario nuevo) y
otros del seed sintético (owner 架空 太郎, 年度 2025 OPEN).
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.session import create_db_engine, get_db, get_session_factory
from app.domain.accounting import balance_sheet
from app.main import app
from app.models import Base
from app.models.entities import (
    Deduction,
    FiscalYear,
    IncomeSource,
    JournalEntry,
    OpeningBalance,
    Taxpayer,
    Transaction,
)
from app.models.enums import FiscalYearStatus, TransactionStatus
from app.seed.dev_seed import seed_dev_data
from app.services.fiscal_years import resolve_active_fiscal_year


def _make_client(*, seeded: bool) -> tuple[TestClient, Engine, object]:
    """Crea un cliente sobre SQLite en memoria, con o sin seed sintético.

    Args:
        seeded: Si ``True`` siembra el perfil sintético (ejemplo, 年度 2025 OPEN).

    Returns:
        Tupla ``(client, engine, factory)``.
    """
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)

    if seeded:
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
    return TestClient(app), engine, factory


@pytest.fixture
def fresh_client() -> Generator[tuple[TestClient, object], None, None]:
    """Cliente sobre BD VACÍA (sin Taxpayer ni 年度)."""
    client, engine, factory = _make_client(seeded=False)
    try:
        yield client, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def seeded_client() -> Generator[tuple[TestClient, object], None, None]:
    """Cliente sobre el seed sintético (ejemplo, 年度 2025 OPEN)."""
    client, engine, factory = _make_client(seeded=True)
    try:
        yield client, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_filing_type_is_explicit_per_year_and_locked_years_are_unchanged(
    fresh_client: tuple[TestClient, object],
) -> None:
    client, _factory = fresh_client
    assert client.post("/api/v1/fiscal-years", json={"year": 2025}).status_code == 200
    assert client.post("/api/v1/fiscal-years", json={"year": 2026}).status_code == 200
    previous = client.get("/api/v1/fiscal-years/2025/filing-type").json()
    assert previous["source"] == "profile_unconfirmed"
    assert client.put("/api/v1/fiscal-years/2026/filing-type", json={
        "value": "shiroiro", "backup_confirmed": False,
    }).status_code == 422
    result = client.put("/api/v1/fiscal-years/2026/filing-type", json={
        "value": "shiroiro", "backup_confirmed": True,
    })
    assert result.status_code == 200
    assert result.json() == {"value": "shiroiro", "source": "year"}
    assert client.get("/api/v1/fiscal-years/2025/filing-type").json() == previous
    assert client.patch("/api/v1/fiscal-years/2026", json={"status": "closed"}).status_code == 200
    assert client.put("/api/v1/fiscal-years/2026/filing-type", json={
        "value": "aoiro_65", "backup_confirmed": True,
    }).status_code == 409
    assert client.get("/api/v1/fiscal-years/2026/filing-type").json() == result.json()


def test_list_empty_db_has_no_years(
    fresh_client: tuple[TestClient, object],
) -> None:
    """Sin Taxpayer => lista vacía, active_year=None."""
    client, _ = fresh_client
    res = client.get("/api/v1/fiscal-years")
    assert res.status_code == 200, res.text
    assert res.json() == {"years": [], "active_year": None}


def test_list_seed_has_2025_open_active(
    seeded_client: tuple[TestClient, object],
) -> None:
    """El seed sintético expone 年度 2025 OPEN como año activo."""
    client, _ = seeded_client
    res = client.get("/api/v1/fiscal-years")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["active_year"] == 2025
    assert {"year": 2025, "status": "open", "rules_available": True} in body["years"]


def test_estimated_prepayment_is_optional_and_updates_filing(
    seeded_client: tuple[TestClient, object],
) -> None:
    client, _ = seeded_client
    url = "/api/v1/fiscal-years/2025/estimated-prepayment"
    before = client.get(url)
    assert before.json() == {"amount": None}
    assert before.headers["cache-control"] == "no-store"
    first = client.post("/api/v1/filing/draft?year=2025").json()
    assert client.put(url, json={"amount": 10_000}).json() == {"amount": 10_000}
    second = client.post("/api/v1/filing/draft?year=2025").json()
    assert second["final_amount"] == first["final_amount"] - 10_000
    assert next(item for item in second["checklist"] if item["key"] == "prepayment_known")["done"]
    assert client.put(url, json={"amount": -1}).status_code == 422
    assert client.patch("/api/v1/fiscal-years/2025", json={"status": "closed"}).status_code == 200
    assert client.put(url, json={"amount": 0}).status_code == 409
    assert client.get(url).json() == {"amount": 10_000}


def test_create_year_is_idempotent(
    seeded_client: tuple[TestClient, object],
) -> None:
    """`POST` crea el 年度 nuevo y, repetido, NO lo duplica."""
    client, factory = seeded_client
    first = client.post("/api/v1/fiscal-years", json={"year": 2026})
    assert first.status_code == 200, first.text
    assert first.json() == {"year": 2026, "status": "open", "rules_available": True}

    # Reenviar el mismo año: idempotente (lo devuelve, no crea otro).
    second = client.post("/api/v1/fiscal-years", json={"year": 2026})
    assert second.status_code == 200, second.text

    db: Session = factory()
    try:
        rows = db.scalars(select(FiscalYear).where(FiscalYear.year == 2026)).all()
        assert len(rows) == 1
    finally:
        db.close()

    # El listado ahora trae 2026 ordenado primero (desc).
    years = client.get("/api/v1/fiscal-years").json()["years"]
    assert years[0]["year"] == 2026
    assert client.get("/api/v1/fiscal-years").json()["active_year"] == 2026


def test_create_year_on_empty_db_creates_taxpayer(
    fresh_client: tuple[TestClient, object],
) -> None:
    """En BD vacía, `POST` crea el Taxpayer junto al primer 年度."""
    client, factory = fresh_client
    res = client.post("/api/v1/fiscal-years", json={"year": 2025})
    assert res.status_code == 200, res.text
    assert res.json() == {"year": 2025, "status": "open", "rules_available": True}

    db: Session = factory()
    try:
        assert len(db.scalars(select(Taxpayer)).all()) == 1
        assert len(db.scalars(select(FiscalYear)).all()) == 1
    finally:
        db.close()


def test_patch_status_filed(
    seeded_client: tuple[TestClient, object],
) -> None:
    """`PATCH` cambia el status del 年度 (open -> filed)."""
    client, _ = seeded_client
    res = client.patch("/api/v1/fiscal-years/2025", json={"status": "filed"})
    assert res.status_code == 200, res.text
    assert res.json() == {"year": 2025, "status": "filed", "rules_available": True}

    # El nuevo ejercicio abierto tiene reglas y desplaza al ejercicio presentado.
    client.post("/api/v1/fiscal-years", json={"year": 2026})
    body = client.get("/api/v1/fiscal-years").json()
    assert body["active_year"] == 2026


def test_patch_unknown_year_404(
    seeded_client: tuple[TestClient, object],
) -> None:
    """`PATCH` de un 年度 inexistente devuelve 404."""
    client, _ = seeded_client
    res = client.patch("/api/v1/fiscal-years/1999", json={"status": "closed"})
    assert res.status_code == 404, res.text
    assert res.json()["detail"]["code"] == "no_fiscal_year"


def test_resolve_active_prefers_open(
    seeded_client: tuple[TestClient, object],
) -> None:
    """`resolve_active_fiscal_year` prefiere el OPEN más reciente sobre el último."""
    client, factory = seeded_client
    # 2025 OPEN (seed). Abrimos 2026 y lo cerramos; 2025 sigue siendo el activo.
    client.post("/api/v1/fiscal-years", json={"year": 2026})
    client.patch("/api/v1/fiscal-years/2026", json={"status": "closed"})

    db: Session = factory()
    try:
        active = resolve_active_fiscal_year(db)
        assert active is not None
        assert active.year == 2025
        assert FiscalYearStatus(active.status) == FiscalYearStatus.OPEN
    finally:
        db.close()


def test_opening_balances_create_journal_and_balance_sheet(
    seeded_client: tuple[TestClient, object],
) -> None:
    """`POST /opening-balances` persiste saldos y genera un 仕訳 balanceado."""
    client, factory = seeded_client
    client.post("/api/v1/fiscal-years", json={"year": 2026})

    res = client.post(
        "/api/v1/fiscal-years/2026/opening-balances",
        json={
            "balances": [
                {"account_code": "101", "amount": 1_000_000},
                {"account_code": "102", "amount": 500_000},
                {"account_code": "201", "amount": 200_000},
                {"account_code": "301", "amount": 1_300_000},
            ]
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["is_balanced"] is True
    assert body["total_assets"] == 1_500_000
    assert body["total_liabilities"] == 200_000
    assert body["total_equity"] == 1_300_000
    assert body["journal_entry_id"] is not None

    db: Session = factory()
    try:
        fy = db.scalars(select(FiscalYear).where(FiscalYear.year == 2026)).one()
        assert len(db.scalars(select(OpeningBalance)).all()) == 4
        entries = db.scalars(
            select(JournalEntry).where(JournalEntry.created_by == "opening_balance")
        ).all()
        assert len(entries) == 1
        assert len(entries[0].lines) == 4

        bs = balance_sheet(db, fy)
        assert bs.total_assets == 1_500_000
        assert bs.total_liabilities == 200_000
        assert bs.total_equity == 1_300_000
        assert bs.is_balanced is True
    finally:
        db.close()


def test_opening_balances_reject_unbalanced_without_writing(
    seeded_client: tuple[TestClient, object],
) -> None:
    """Un payload que no cumple 資産 = 負債 + 資本 devuelve 422 sin escribir."""
    client, factory = seeded_client
    client.post("/api/v1/fiscal-years", json={"year": 2026})

    res = client.post(
        "/api/v1/fiscal-years/2026/opening-balances",
        json={
            "balances": [
                {"account_code": "101", "amount": 1_000_000},
                {"account_code": "301", "amount": 900_000},
            ]
        },
    )
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["code"] == "opening_balance_unbalanced"

    db: Session = factory()
    try:
        assert db.scalars(select(OpeningBalance)).all() == []
        opening_entries = db.scalars(
            select(JournalEntry).where(JournalEntry.created_by == "opening_balance")
        ).all()
        assert opening_entries == []
    finally:
        db.close()


def test_opening_balances_replace_existing_without_duplicates(
    seeded_client: tuple[TestClient, object],
) -> None:
    """Reenviar saldos reemplaza los anteriores y recrea un solo 仕訳."""
    client, factory = seeded_client
    client.post("/api/v1/fiscal-years", json={"year": 2026})

    first = {
        "balances": [
            {"account_code": "101", "amount": 1_000_000},
            {"account_code": "301", "amount": 1_000_000},
        ]
    }
    second = {
        "balances": [
            {"account_code": "102", "amount": 750_000},
            {"account_code": "301", "amount": 750_000},
        ]
    }
    first_res = client.post("/api/v1/fiscal-years/2026/opening-balances", json=first)
    assert first_res.status_code == 200, first_res.text
    res = client.post("/api/v1/fiscal-years/2026/opening-balances", json=second)
    assert res.status_code == 200, res.text
    assert res.json()["total_assets"] == 750_000

    db: Session = factory()
    try:
        rows = db.scalars(select(OpeningBalance)).all()
        entries = db.scalars(
            select(JournalEntry).where(JournalEntry.created_by == "opening_balance")
        ).all()
        assert len(rows) == 2
        assert len(entries) == 1
        assert {line.account.code for line in entries[0].lines} == {"102", "301"}
    finally:
        db.close()


def test_opening_balances_are_locked_after_year_closes(
    seeded_client: tuple[TestClient, object],
) -> None:
    """Cerrar el 年度 conserva su apertura e impide reemplazarla."""
    client, _ = seeded_client
    client.post("/api/v1/fiscal-years", json={"year": 2026})
    original = {
        "balances": [
            {"account_code": "101", "amount": 600_000},
            {"account_code": "301", "amount": 600_000},
        ]
    }
    created = client.post("/api/v1/fiscal-years/2026/opening-balances", json=original)
    assert created.status_code == 200, created.text
    entry_id = created.json()["journal_entry_id"]

    closed = client.patch("/api/v1/fiscal-years/2026", json={"status": "closed"})
    assert closed.status_code == 200, closed.text
    rejected = client.post(
        "/api/v1/fiscal-years/2026/opening-balances",
        json={
            "balances": [
                {"account_code": "102", "amount": 900_000},
                {"account_code": "301", "amount": 900_000},
            ]
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"] == {
        "code": "fiscal_year_locked",
        "message": "締切済み・申告済みの年度は変更できません。再開してから編集してください。",
        "details": {"year": 2026, "status": "closed"},
    }

    persisted = client.get("/api/v1/fiscal-years/2026/opening-balances")
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["total_assets"] == 600_000
    assert persisted.json()["journal_entry_id"] == entry_id


def test_multi_year_opening_balance_cycle_keeps_years_isolated(
    seeded_client: tuple[TestClient, object],
) -> None:
    """Crear, cerrar y abrir el siguiente 年度 no mezcla saldos ni 仕訳."""
    client, factory = seeded_client
    for year, amount, asset_code in (
        (2026, 700_000, "101"),
        (2027, 850_000, "102"),
    ):
        created = client.post("/api/v1/fiscal-years", json={"year": year})
        assert created.status_code == 200, created.text
        opening = client.post(
            f"/api/v1/fiscal-years/{year}/opening-balances",
            json={
                "balances": [
                    {"account_code": asset_code, "amount": amount},
                    {"account_code": "301", "amount": amount},
                ]
            },
        )
        assert opening.status_code == 200, opening.text
        if year == 2026:
            closed = client.patch(
                "/api/v1/fiscal-years/2026", json={"status": "closed"}
            )
            assert closed.status_code == 200, closed.text

    first = client.get("/api/v1/fiscal-years/2026/opening-balances").json()
    second = client.get("/api/v1/fiscal-years/2027/opening-balances").json()
    assert first["total_assets"] == 700_000
    assert second["total_assets"] == 850_000
    assert first["journal_entry_id"] != second["journal_entry_id"]

    db: Session = factory()
    try:
        years = {
            fy.year: fy
            for fy in db.scalars(
                select(FiscalYear).where(FiscalYear.year.in_([2026, 2027]))
            ).all()
        }
        assert FiscalYearStatus(years[2026].status) == FiscalYearStatus.CLOSED
        assert FiscalYearStatus(years[2027].status) == FiscalYearStatus.OPEN
        assert len(years[2026].opening_balances) == 2
        assert len(years[2027].opening_balances) == 2
    finally:
        db.close()


def test_closed_year_rejects_all_core_financial_mutations(
    seeded_client: tuple[TestClient, object],
) -> None:
    """Un 年度 cerrado bloquea CRUD, imports, onboarding y revisión de recibos."""
    client, factory = seeded_client
    income = client.post(
        "/api/v1/income-sources",
        params={"year": 2025},
        json={"income_type": "zatsu", "gross": 120_000},
    ).json()
    deduction = client.post(
        "/api/v1/deductions",
        params={"year": 2025},
        json={"type": "ideco", "amount": 60_000},
    ).json()

    db: Session = factory()
    try:
        fiscal_year = db.scalars(select(FiscalYear).where(FiscalYear.year == 2025)).one()
        fiscal_year_id = str(fiscal_year.id)
        taxpayer_name = fiscal_year.taxpayer.name
        income_count = len(db.scalars(select(IncomeSource)).all())
        deduction_count = len(db.scalars(select(Deduction)).all())
        transaction_count = len(db.scalars(select(Transaction)).all())
    finally:
        db.close()

    imported = client.post(
        "/api/v1/import/csv/commit",
        json={
            "fiscal_year_id": fiscal_year_id,
            "rows": [
                {
                    "dedup_hash": "before-lock-2025-07-01-2000",
                    "date": "2025-07-01",
                    "vendor": "ロック前取引",
                    "total_amount": 2_000,
                    "account_code": "501",
                    "tax_lines": [],
                }
            ],
        },
    )
    assert imported.status_code == 200, imported.text
    transaction_id = imported.json()["transaction_ids"][0]

    closed = client.patch("/api/v1/fiscal-years/2025", json={"status": "closed"})
    assert closed.status_code == 200, closed.text

    attempts = [
        client.post(
            "/api/v1/income-sources",
            params={"year": 2025},
            json={"income_type": "fudosan", "gross": 300_000},
        ),
        client.patch(f"/api/v1/income-sources/{income['id']}", json={"gross": 999_999}),
        client.delete(f"/api/v1/income-sources/{income['id']}"),
        client.post(
            "/api/v1/deductions",
            params={"year": 2025},
            json={"type": "jishin_hoken", "amount": 20_000},
        ),
        client.patch(f"/api/v1/deductions/{deduction['id']}", json={"amount": 99_999}),
        client.delete(f"/api/v1/deductions/{deduction['id']}"),
        client.patch(
            f"/api/v1/receipts/{transaction_id}", json={"vendor": "改変不可"}
        ),
        client.post(f"/api/v1/receipts/{transaction_id}/confirm"),
        client.post(
            "/api/v1/receipts/batch-confirm",
            json={"transaction_ids": [transaction_id]},
        ),
        client.post(
            "/api/v1/receipts",
            data={"fiscal_year_id": fiscal_year_id},
            files={"file": ("receipt.jpg", b"not-processed", "image/jpeg")},
        ),
        client.post(
            "/api/v1/import/csv/commit",
            json={
                "rows": [
                    {
                        "dedup_hash": "after-lock-2025-07-02-3000",
                        "date": "2025-07-02",
                        "vendor": "締切後取引",
                        "total_amount": 3_000,
                    }
                ]
            },
        ),
        client.post(
            "/api/v1/deductions/import-xml/commit",
            params={"year": 2025},
            json={"deduction_type": "furusato", "amount": 10_000},
        ),
        client.post(
            "/api/v1/onboarding/complete",
            params={"year": 2025},
            json={"name": "変更されない氏名"},
        ),
        client.post(
            "/api/v1/fiscal-years/2025/opening-balances",
            json={"balances": []},
        ),
    ]
    for response in attempts:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "fiscal_year_locked"

    db = factory()
    try:
        persisted_income = db.get(IncomeSource, income["id"])
        persisted_deduction = db.get(Deduction, deduction["id"])
        persisted_transaction = db.get(Transaction, transaction_id)
        taxpayer = db.scalars(select(Taxpayer)).one()
        assert persisted_income is not None and persisted_income.gross == 120_000
        assert persisted_deduction is not None and persisted_deduction.amount == 60_000
        assert persisted_transaction is not None
        assert persisted_transaction.vendor == "ロック前取引"
        assert TransactionStatus(persisted_transaction.status) == TransactionStatus.PENDING
        assert taxpayer.name == taxpayer_name
        assert len(db.scalars(select(IncomeSource)).all()) == income_count
        assert len(db.scalars(select(Deduction)).all()) == deduction_count
        assert len(db.scalars(select(Transaction)).all()) == transaction_count + 1
    finally:
        db.close()
