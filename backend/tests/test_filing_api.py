"""Tests del router del 確定申告 (Fase 3B-2): draft, PDF, .xtx, CSV.

Cubren:
    - El draft calcula bien (el 納付額 cuadra con /tax/calculate, mismo income).
    - Los 4 PDF se generan sin error (200, application/pdf, no vacios).
    - El .xtx es XML valido con el 納付額 correcto.
    - El CSV es SHIFT-JIS decodificable.
    - El 貸借対照表 cuadra (資産 = 負債 + 資本 + 所得).

Usan SQLite en memoria con el escenario de seed (taxpayer + 年度 2025 +
transacciones OCR) confirmando las transacciones, sin dependencias externas.
"""

from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Generator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import app
from app.models import Base, Transaction
from app.models.enums import TransactionStatus
from app.seed.dev_seed import (
    DEMO_IDECO,
    DEMO_SOCIAL_INSURANCE,
    DEMO_WITHHOLDING_TAX,
    seed_demo_data,
)
from app.services.forms.drafting import build_filing_draft


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Cliente de test con el escenario de seed y todas las transacciones confirmadas.

    Yields:
        `TestClient` con `get_db` override-ado a una BD SQLite en memoria.
    """
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)

    session: Session = factory()
    seed_demo_data(session)
    # Confirmar todas las transacciones (entran al PL).
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
def session() -> Generator[Session, None, None]:
    """Sesion directa con el seed confirmado (para tests de servicio puro)."""
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = get_session_factory(engine)()
    seed_demo_data(db)
    for tx in db.query(Transaction).all():
        tx.status = TransactionStatus.CONFIRMED
    db.commit()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


# --- Draft ----------------------------------------------------------------


def test_confirmed_year_filing_type_changes_calculation_only_for_that_year(
    client: TestClient,
) -> None:
    assert client.post("/api/v1/fiscal-years", json={"year": 2026}).status_code == 200
    baseline = client.post("/api/v1/filing/draft?year=2025").json()
    assert baseline["filing_type"] == "aoiro_65"
    assert baseline["aoiro_deduction"] > 0
    assert client.put("/api/v1/fiscal-years/2025/filing-type", json={
        "value": "shiroiro", "backup_confirmed": True,
    }).status_code == 200
    updated = client.post("/api/v1/filing/draft?year=2025").json()
    assert updated["filing_type"] == "shiroiro"
    assert updated["aoiro_deduction"] == 0
    other = client.get("/api/v1/fiscal-years/2026/filing-type").json()
    assert other == {"value": "aoiro_65", "source": "profile_unconfirmed"}


@pytest.mark.parametrize("office_key", [None, "unknown-office"])
def test_unknown_tax_office_is_not_replaced_with_tsushima(
    client: TestClient, office_key: str | None,
) -> None:
    from app.models.entities import Taxpayer

    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        db.query(Taxpayer).one().filing_office = office_key
        db.commit()
    finally:
        generator.close()
    draft = client.post("/api/v1/filing/draft?year=2025")
    assert draft.status_code == 200
    draft_id = draft.json()["draft_id"]
    pdf = client.get(f"/api/v1/filing/{draft_id}/pdf?form=shinkokusho")
    assert pdf.status_code == 200
    import pymupdf
    with pymupdf.open(stream=pdf.content, filetype="pdf") as document:
        assert "津島" not in document[0].get_text(clip=pymupdf.Rect(55, 20, 130, 43))
    xtx = client.get(f"/api/v1/filing/{draft_id}/xtx")
    assert xtx.status_code == 409
    assert xtx.json()["detail"]["code"] == "tax_office_unrecognized"
    package = client.get(f"/api/v1/filing/{draft_id}/official-package")
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert not any(name.endswith(".xtx") for name in archive.namelist())
        assert "oficina fiscal" in archive.read("00_LEER_REVISION.txt").decode("utf-8")


def test_draft_returns_structured_summary(client: TestClient) -> None:
    """El POST /filing/draft devuelve el resumen con todos los numeros."""
    resp = client.post("/api/v1/filing/draft?year=2025")
    assert resp.status_code == 200
    body = resp.json()
    assert body["year"] == 2025
    assert body["filing_type"] == "aoiro_65"
    assert body["confirmed_count"] == 12
    assert body["pending_count"] == 0
    assert body["sales_revenue"] == 6_800_000
    assert body["aoiro_deduction"] == 650_000
    # 事業所得 = (売上 − 経費) − 青色65万.
    assert body["business_income"] == body["pl_net_income"] - 650_000
    assert body["bs_balanced"] is True
    assert len(body["checklist"]) == 4
    checks = {item["key"]: item for item in body["checklist"]}
    assert checks["prepayment_known"]["done"] is False
    assert checks["forms_ready"]["done"] is False


def test_repeated_drafts_preserve_opening_balances(client: TestClient) -> None:
    response = client.post(
        "/api/v1/fiscal-years/2025/opening-balances",
        json={"balances": [{"account_code": "101", "amount": 1_000_000},
                           {"account_code": "301", "amount": 1_000_000}]},
    )
    assert response.status_code == 200, response.text
    original_id = response.json()["journal_entry_id"]
    for _ in range(2):
        draft = client.post("/api/v1/filing/draft?year=2025")
        assert draft.status_code == 200, draft.text
    opening = client.get("/api/v1/fiscal-years/2025/opening-balances")
    assert opening.status_code == 200, opening.text
    assert opening.json()["journal_entry_id"] == original_id


def test_unknown_journal_origin_blocks_recalculation_without_deleting(session: Session) -> None:
    from sqlalchemy import select

    from app.models.entities import FiscalYear, JournalEntry
    from app.services.forms.drafting import UnidentifiedJournalEntriesError

    fy = session.scalars(select(FiscalYear).where(FiscalYear.year == 2025)).one()
    legacy = JournalEntry(fiscal_year_id=fy.id, date=date(2025, 1, 1),
                          description="Asiento anterior sin identificar")
    session.add(legacy)
    session.commit()
    legacy_id = legacy.id
    with pytest.raises(UnidentifiedJournalEntriesError):
        build_filing_draft(session, 2025)
    assert session.get(JournalEntry, legacy_id) is not None


def test_api_reports_unknown_journal_origin_without_deleting(client: TestClient) -> None:
    from app.db.session import get_db
    from app.models.entities import Account, FiscalYear, JournalEntry, JournalLine

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    fy = db.query(FiscalYear).filter_by(year=2025).one()
    legacy = JournalEntry(fiscal_year_id=fy.id, date=date(2025, 1, 1), description="Anterior")
    account = db.query(Account).filter_by(code="101").one()
    legacy.lines = [JournalLine(side="debit", account_id=account.id, amount=1234)]
    db.add(legacy)
    db.commit()
    legacy_id = legacy.id
    response = client.post("/api/v1/filing/draft?year=2025")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "journal_origin_unknown"
    review = client.get("/api/v1/filing/journal-review?year=2025")
    assert review.status_code == 200
    assert review.headers["cache-control"] == "no-store"
    assert [entry["id"] for entry in review.json()["entries"]] == [str(legacy_id)]
    assert review.json()["entries"][0]["description"] == "Anterior"
    assert review.json()["entries"][0]["lines"][0]["amount"] == 1234
    fingerprint = review.json()["entries"][0]["fingerprint"]
    endpoint = f"/api/v1/filing/journal-review/{legacy_id}/origin?year=2025"
    stale = client.post(endpoint, json={"origin": "manual", "backup_confirmed": True,
                                        "fingerprint": "0" * 64})
    assert stale.status_code == 409
    assert db.get(JournalEntry, legacy_id).created_by is None
    missing_backup = client.post(endpoint, json={"origin": "manual", "backup_confirmed": False,
                                                 "fingerprint": fingerprint})
    assert missing_backup.status_code == 422
    saved = client.post(endpoint, json={"origin": "manual", "backup_confirmed": True,
                                        "fingerprint": fingerprint})
    assert saved.status_code == 200
    db.expire_all()
    assert db.get(JournalEntry, legacy_id).created_by == "user_reviewed_manual"
    assert client.post(endpoint, json={"origin": "manual", "backup_confirmed": True,
                                       "fingerprint": fingerprint}).status_code == 409
    from app.models.entities import AuditLog
    assert db.query(AuditLog).filter_by(
        entity_id=str(legacy_id), action="origin_review"
    ).count() == 1
    assert db.get(JournalEntry, legacy_id) is not None
    db_gen.close()


def test_marking_projection_regenerates_only_after_recalculation(client: TestClient) -> None:
    from app.db.session import get_db
    from app.models.entities import FiscalYear, JournalEntry
    from app.services.forms.drafting import PROJECTION_CREATED_BY

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    fy = db.query(FiscalYear).filter_by(year=2025).one()
    entry = JournalEntry(fiscal_year_id=fy.id, date=date(2025, 1, 1), description="Anterior")
    db.add(entry)
    db.commit()
    entry_id = entry.id
    snapshot = client.get("/api/v1/filing/journal-review?year=2025").json()["entries"][0]
    url = f"/api/v1/filing/journal-review/{entry_id}/origin?year=2025"
    response = client.post(url, json={"origin": "projection", "backup_confirmed": True,
                                      "fingerprint": snapshot["fingerprint"]})
    assert response.status_code == 200
    db.expire_all()
    assert db.get(JournalEntry, entry_id).created_by == PROJECTION_CREATED_BY
    assert client.post("/api/v1/filing/draft?year=2025").status_code == 200
    db.expire_all()
    assert db.get(JournalEntry, entry_id) is None
    db_gen.close()


def test_mixed_expense_reaches_ledger_and_preserves_original(session: Session) -> None:
    from sqlalchemy import select

    from app.models.entities import FiscalYear, JournalEntry, JournalLine
    from app.models.enums import JournalSide

    baseline = build_filing_draft(session, 2025)
    fy = session.scalars(select(FiscalYear).where(FiscalYear.year == 2025)).one()
    tx = Transaction(
        fiscal_year_id=fy.id, date=date(2025, 9, 1), vendor="Ejemplo mixto",
        total_amount=700_000, source="csv", status=TransactionStatus.CONFIRMED,
        account_code="599", is_qualified_invoice=True,
        tax_lines=[{"base": 500_000, "tax": 50_000, "rate": 10},
                   {"base": 138_889, "tax": 11_111, "rate": 8}],
        business_allocation={"original_total": 700_000, "numerator": 3,
                             "denominator": 10, "rationale": "Registro de viajes"},
    )
    session.add(tx)
    session.flush()
    result = build_filing_draft(session, 2025)
    assert result.confirmed_expense_total == baseline.confirmed_expense_total + 210_000
    assert result.income_statement.net_income == baseline.income_statement.net_income - 210_000
    assert tx.total_amount == 700_000
    entry = session.scalars(select(JournalEntry).where(JournalEntry.transaction_id == tx.id)).one()
    debits = [line for line in entry.lines if line.side == JournalSide.DEBIT]
    assert sum(line.amount for line in debits) == 210_000
    assert {line.tax_rate for line in debits} == {8, 10}
    assert sum(line.amount for line in entry.lines if line.side == JournalSide.CREDIT) == 210_000
    assert session.scalars(select(JournalLine).where(JournalLine.entry_id == entry.id)).all()


def test_mixed_allocation_api_requires_valid_pending_receipt(client: TestClient) -> None:
    receipts = client.get("/api/v1/receipts?year=2025&status=confirmed").json()
    tx = next(item for item in receipts if all(
        isinstance(line.get("base"), int) and isinstance(line.get("tax"), int)
        for line in item["tax_lines"]
    ) and sum(line["base"] + line["tax"] for line in item["tax_lines"]) == item["total_amount"])
    tx_id, original = tx["id"], tx["total_amount"]
    url = f"/api/v1/receipts/{tx_id}/business-allocation"
    payload = {"expected_total": original, "numerator": 3, "denominator": 10,
               "rationale": "Kilómetros registrados"}
    assert client.put(url, json=payload).status_code == 409
    assert client.patch(f"/api/v1/receipts/{tx_id}", json={"status": "pending"}).status_code == 200
    assert client.put(url, json={**payload, "expected_total": original + 1}).status_code == 409
    assert client.put(url, json={**payload, "numerator": 11}).status_code == 422
    saved = client.put(url, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["total_amount"] == original
    assert saved.json()["business_allocation"]["numerator"] == 3
    modified = client.patch(f"/api/v1/receipts/{tx_id}", json={"total_amount": original + 1})
    assert modified.status_code == 409
    assert client.post(f"/api/v1/receipts/{tx_id}/confirm", json={}).status_code == 200
    assert client.put(url, json=payload).status_code == 409


def test_mixed_allocation_rejects_closed_fiscal_year(client: TestClient) -> None:
    receipts = client.get("/api/v1/receipts?year=2025&status=confirmed").json()
    tx = receipts[0]
    response = client.patch(f"/api/v1/receipts/{tx['id']}", json={"status": "pending"})
    assert response.status_code == 200
    assert client.patch("/api/v1/fiscal-years/2025", json={"status": "closed"}).status_code == 200
    result = client.put(
        f"/api/v1/receipts/{tx['id']}/business-allocation",
        json={"expected_total": tx["total_amount"], "numerator": 1,
              "denominator": 2, "rationale": "Registro de viajes"},
    )
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "fiscal_year_locked"


def test_registration_number_correction_checks_staleness_and_audits(client: TestClient) -> None:
    from app.db.session import get_db
    from app.models.entities import AuditLog
    from app.services.ocr.parsers.reg_number import validate_checksum

    tx = client.get("/api/v1/receipts?year=2025&status=confirmed").json()[0]
    pending = client.patch(f"/api/v1/receipts/{tx['id']}", json={"status": "pending"})
    assert pending.status_code == 200
    url = f"/api/v1/receipts/{tx['id']}/registration-number"
    number = "T1234567890123"
    stale = client.put(url, json={"expected_number": "wrong", "number": number})
    assert stale.status_code == 409
    invalid = client.put(url, json={"expected_number": tx["registration_number"], "number": "T12"})
    assert invalid.status_code == 422
    direct = client.patch(f"/api/v1/receipts/{tx['id']}", json={"registration_number": number})
    assert direct.status_code == 422
    saved = client.put(url, json={"expected_number": tx["registration_number"], "number": number})
    assert saved.status_code == 200, saved.text
    assert saved.json()["registration_number"] == number
    assert saved.json()["is_qualified_invoice"] is validate_checksum(number[1:])
    repeat = client.put(url, json={"expected_number": tx["registration_number"],
                                   "number": "T0000000000000"})
    assert repeat.status_code == 409
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    assert db.query(AuditLog).filter_by(
        entity_id=tx["id"], action="correct_reg_number"
    ).count() == 1
    assert client.post(f"/api/v1/receipts/{tx['id']}/confirm", json={}).status_code == 200
    confirmed_edit = client.put(url, json={"expected_number": number, "number": "T0000000000000"})
    assert confirmed_edit.status_code == 409
    db_gen.close()


@pytest.mark.parametrize("status", ["closed", "filed"])
def test_locked_year_filing_and_exports_do_not_rewrite_ledger(
    client: TestClient, status: str
) -> None:
    from app.db.session import get_db
    from app.models.entities import FilingDraft, JournalEntry

    created = client.post("/api/v1/filing/draft?year=2025")
    assert created.status_code == 200
    draft_id = created.json()["draft_id"]
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    before_ids = {entry.id for entry in db.query(JournalEntry).all()}
    before_snapshot = dict(db.query(FilingDraft).one().computed or {})
    assert client.patch("/api/v1/fiscal-years/2025", json={"status": status}).status_code == 200
    assert client.post("/api/v1/filing/draft?year=2025").json()["draft_id"] == draft_id
    assert client.get(f"/api/v1/filing/{draft_id}/pdf?form=shiwakecho").status_code == 200
    assert client.get("/api/v1/recommendations/2025").status_code == 200
    db.expire_all()
    assert {entry.id for entry in db.query(JournalEntry).all()} == before_ids
    assert db.query(FilingDraft).one().computed == before_snapshot
    db_gen.close()


def test_closed_year_without_draft_does_not_create_one(client: TestClient) -> None:
    assert client.patch("/api/v1/fiscal-years/2025", json={"status": "closed"}).status_code == 200
    response = client.post("/api/v1/filing/draft?year=2025")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "closed_year_without_draft"


def test_2026_draft_cannot_export_2025_official_forms(client: TestClient) -> None:
    assert client.post("/api/v1/fiscal-years", json={"year": 2026}).status_code == 200
    result = client.post("/api/v1/filing/draft?year=2026")
    assert result.status_code == 200, result.text
    readiness = {item["key"]: item for item in result.json()["checklist"]}
    assert readiness["forms_ready"]["done"] is False
    draft_id = result.json()["draft_id"]
    for suffix in (
        "pdf?form=shinkokusho", "pdf?form=kessansho", "official-package",
        "xtx", "xtx/validation", "csv",
    ):
        response = client.get(f"/api/v1/filing/{draft_id}/{suffix}")
        assert response.status_code == 409, suffix
        assert response.json()["detail"]["code"] == "filing_format_not_verified"
    assert client.get(f"/api/v1/filing/{draft_id}/pdf?form=shiwakecho").status_code == 200


def test_self_disability_entry_rejects_duplicates_and_invalid_amount(client: TestClient) -> None:
    url = "/api/v1/deductions?year=2025"
    invalid = client.post(url, json={"type": "disability_self", "amount": 1})
    assert invalid.status_code == 422
    first = client.post(url, json={"type": "disability_self", "amount": 270_000})
    assert first.status_code == 201
    duplicate = client.post(url, json={"type": "disability_self", "amount": 270_000})
    assert duplicate.status_code == 409
    patch = client.patch(f"/api/v1/deductions/{first.json()['id']}", json={"amount": 1})
    assert patch.status_code == 422
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    assert any(item["type"] == "disability_self" for item in draft["deductions_applied"])
    for path in ("xtx", "xtx/validation"):
        response = client.get(f"/api/v1/filing/{draft['draft_id']}/{path}")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "xtx_incomplete_mapping"
    package = client.get(f"/api/v1/filing/{draft['draft_id']}/official-package")
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert not any(name.endswith(".xtx") for name in archive.namelist())
        assert "NO INCLUYE XTX" in archive.read("00_LEER_REVISION.txt").decode("utf-8")
        manifest = json.loads(archive.read("00_manifest.json"))
        assert manifest["checks"]["xtx_included"] is False
        assert manifest["checks"]["xtx_validation"] is None


def test_xtx_rejects_unmapped_income_source(client: TestClient) -> None:
    created = client.post(
        "/api/v1/income-sources?year=2025",
        json={"income_type": "zatsu", "gross": 200_000, "expenses": 10_000},
    )
    assert created.status_code == 201
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    response = client.get(f"/api/v1/filing/{draft['draft_id']}/xtx")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "xtx_incomplete_mapping"


def test_xtx_internal_disability_field_only_when_unambiguous(session: Session) -> None:
    from app.services.forms.etax_export import build_xtx

    result = build_filing_draft(session, 2025)
    deductions = result.tax.deduction_breakdown
    deductions.ordinary_disability_self = True
    deductions.other = 270_000
    root = ET.fromstring(build_xtx(result))
    assert root.findtext(".//ABB00510") == "270000"
    deductions.other = 540_000
    root = ET.fromstring(build_xtx(result))
    assert root.find(".//ABB00510") is None


def test_official_form_sums_multiple_sources_of_same_kind(session: Session) -> None:
    from app.domain.tax.schemas import IncomeBreakdownItem, IncomeKind
    from app.services.forms.shinkokusho_official import build_dai1_fields

    result = build_filing_draft(session, 2025)
    result.tax.income_breakdown = [
        IncomeBreakdownItem(kind=IncomeKind.FUDOSAN, amount=100_000, label=None),
        IncomeBreakdownItem(kind=IncomeKind.FUDOSAN, amount=200_000, label=None),
        IncomeBreakdownItem(kind=IncomeKind.ZATSU, amount=30_000, label=None),
        IncomeBreakdownItem(kind=IncomeKind.ZATSU, amount=40_000, label=None),
    ]
    fields = build_dai1_fields(result)
    assert next(field.text for field in fields if field.y == 376.4) == "300000"
    assert next(field.text for field in fields if field.y == 491.9) == "70000"


def test_official_pdf_places_self_disability_on_its_own_line(session: Session) -> None:
    from app.services.forms.shinkokusho_official import build_dai1_fields

    result = build_filing_draft(session, 2025)
    result.tax.deduction_breakdown.ordinary_disability_self = True
    result.tax.deduction_breakdown.other = 270_000
    fields = build_dai1_fields(result)
    assert next(field.text for field in fields if field.y == 623.9) == "27"
    assert not any(field.y == 607.4 for field in fields)
    result.tax.deduction_breakdown.ordinary_disability_self = False
    assert not any(field.y in (607.4, 623.9) for field in build_dai1_fields(result))


def test_official_pdf_rounds_positive_declared_tax_but_not_refund(session: Session) -> None:
    from app.services.forms.shinkokusho_official import build_dai1_fields

    result = build_filing_draft(session, 2025)
    result.tax.total_tax = 150_131
    result.tax.withholding_tax = 100_000
    fields = build_dai1_fields(result)
    assert next(field.text for field in fields if field.y == 392.9) == "50100"
    result.tax.withholding_tax = 160_000
    fields = build_dai1_fields(result)
    assert next(field.text for field in fields if field.y == 392.9) == "-9869"


def test_xtx_separates_withholding_and_prepayment(session: Session) -> None:
    from app.domain.tax.income_tax import calculate
    from app.domain.tax.schemas import (
        DeductionInput,
        IncomeInput,
        IncomeKind,
        TaxCalculationInput,
        WithholdingInput,
    )
    from app.services.forms.etax_export import build_xtx

    result = build_filing_draft(session, 2025)
    result.tax = calculate(TaxCalculationInput(
        year=2025, incomes=[IncomeInput(kind=IncomeKind.JIGYO, amount=5_000_000)],
        deductions=DeductionInput(social_insurance=600_000),
        withholding=WithholdingInput(withholding_tax=100_000, estimated_prepayment=240_000),
    ))
    root = ET.fromstring(build_xtx(result))
    assert root.findtext(".//ABB00710") == "100000"
    assert root.findtext(".//ABB00720") == "233300"
    assert root.findtext(".//ABB00730") == "240000"
    assert root.findtext(".//ABB00760") == "6700"


def test_draft_matches_tax_calculate(client: TestClient) -> None:
    """El 納付額 del draft cuadra con /tax/calculate (mismo income + 控除 demo).

    El seed demo carga 社会保険料控除 ¥300,000 + iDeCo ¥276,000 (el 基礎控除 lo
    calcula la calculadora). Para que la comparacion sea apples-to-apples se
    pasan esas mismas 控除 al /tax/calculate.
    """
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    calc = client.post(
        "/api/v1/tax/calculate",
        json={
            "year": 2025,
            "filing_type": "aoiro_65",
            "incomes": [{"kind": "jigyo", "amount": draft["business_income"]}],
            "deductions": {
                "social_insurance": DEMO_SOCIAL_INSURANCE,
                "ideco": DEMO_IDECO,
            },
            "withholding": {"withholding_tax": DEMO_WITHHOLDING_TAX},
        },
    ).json()
    assert draft["final_amount"] == calc["final_amount"]
    assert draft["final_amount"] == 95_200  # 納付額 tras redondeo legal
    assert draft["total_tax"] == calc["total_tax"]
    assert draft["taxable_income"] == calc["taxable_income"]


def test_draft_unsupported_year_400(client: TestClient) -> None:
    """Un anio sin parametros fiscales devuelve 400."""
    resp = client.post("/api/v1/filing/draft?year=1999")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_fiscal_year"


# --- Summary --------------------------------------------------------------


def test_summary_roundtrip(client: TestClient) -> None:
    """GET /filing/{id}/summary devuelve el mismo 納付額 que el draft."""
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    summary = client.get(f"/api/v1/filing/{draft['draft_id']}/summary").json()
    assert summary["final_amount"] == draft["final_amount"]
    assert summary["draft_id"] == draft["draft_id"]


def test_summary_not_found_404(client: TestClient) -> None:
    """Un draft_id inexistente devuelve 404."""
    resp = client.get("/api/v1/filing/00000000-0000-0000-0000-000000000000/summary")
    assert resp.status_code == 404


# --- PDF ------------------------------------------------------------------


@pytest.mark.parametrize(
    "form", ["shinkokusho", "kessansho", "shiwakecho", "motocho"]
)
def test_pdf_generates(client: TestClient, form: str) -> None:
    """Cada formulario PDF se genera (200, application/pdf, no vacio, magic %PDF)."""
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    resp = client.get(f"/api/v1/filing/{draft['draft_id']}/pdf?form={form}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["cache-control"] == "no-store"
    assert len(resp.content) > 1000
    assert resp.content[:5] == b"%PDF-"


def test_pdf_unknown_form_400(client: TestClient) -> None:
    """Un formulario desconocido devuelve 400."""
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    resp = client.get(f"/api/v1/filing/{draft['draft_id']}/pdf?form=nope")
    assert resp.status_code == 400


@pytest.mark.parametrize(
    ("form", "renderer"),
    [("shinkokusho", "render_shinkokusho_official"),
     ("kessansho", "render_kessansho_official")],
)
def test_missing_official_template_never_silently_returns_replica(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, form: str, renderer: str,
) -> None:
    import app.api.filing as filing_api

    def missing(_result: object) -> bytes:
        raise FileNotFoundError("simulated")

    monkeypatch.setattr(filing_api, renderer, missing)
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    response = client.get(f"/api/v1/filing/{draft['draft_id']}/pdf?form={form}")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "official_template_missing"


def test_official_package_missing_file_returns_clear_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.filing as filing_api

    def missing(*_args: object, **_kwargs: object) -> bytes:
        raise FileNotFoundError("simulated")

    monkeypatch.setattr(filing_api, "build_official_package", missing)
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    response = client.get(f"/api/v1/filing/{draft['draft_id']}/official-package")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "official_package_file_missing"


# --- .xtx (XML) -----------------------------------------------------------


def test_xtx_is_valid_xml(client: TestClient) -> None:
    """El .xtx es el sobre oficial KOA020 (VR 23.0) y parsea como XML."""
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    resp = client.get(f"/api/v1/filing/{draft['draft_id']}/xtx")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert "xml" in resp.headers["content-type"]
    # (a) parsea como XML; (e) encoding UTF-8 declarado standalone="no".
    assert b'encoding="UTF-8"' in resp.content
    assert b'standalone="no"' in resp.content
    root = ET.fromstring(resp.content)
    # (b) raíz <DATA> con <KOA020 VR="23.0">.
    assert root.tag == "DATA"
    form = root.find("KOA020")
    assert form is not None
    assert form.attrib["VR"] == "23.0"
    # (d) NO hay bloque KOA210 / 決算書 en el XML.
    assert root.find(".//KOA210") is None
    # 合計所得金額 (ABB00410) y 申告納税額 (ABB00720) presentes con el valor del demo.
    assert root.find(".//ABB00410").text == str(draft["total_income"])
    assert root.find(".//ABB00720").text is not None


def test_xtx_owner_real_case_r7() -> None:
    """El .xtx del ejemplo sintético excluye el crédito rechazado."""
    from app.seed.dev_seed import seed_dev_data
    from app.services.forms.etax_export import build_xtx

    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = get_session_factory(engine)()
    try:
        seed_dev_data(db)
        for tx in db.query(Transaction).all():
            tx.status = TransactionStatus.CONFIRMED
        db.commit()
        draft = build_filing_draft(db, 2025)
        content = build_xtx(draft)

        # (a) parsea como XML; (e) encoding UTF-8.
        assert b'encoding="UTF-8"' in content
        root = ET.fromstring(content)
        # (b) sobre oficial.
        assert root.tag == "DATA"
        koa020 = root.find("KOA020")
        assert koa020 is not None and koa020.attrib["VR"] == "23.0"
        assert koa020.attrib["id"] == "KOA020"
        page1 = koa020.find("KOA020-1")
        assert page1 is not None
        assert page1.find("ABA00000") is not None  # cabecera.
        assert page1.find("ABB00000") is not None  # cuerpo 第一表.

        # 年分 (ABA00010): 令和(5) + 07.
        nenbun = root.find(".//ABA00010")
        assert nenbun.find("Gengo").text == "5"
        assert nenbun.find("Nen").text == "07"
        # 申告の種類 = 1 (確定), 青色区分 = 1.
        assert root.find(".//ABA00020").text == "1"
        assert root.find(".//ABA00240").text == "1"

        # Los importes corresponden al borrador sintético calculado.
        assert root.find(".//ABB00410").text == str(draft.tax.total_income)
        assert root.find(".//ABB00650") is None

        # (d) NO hay bloque KOA210 / 決算書 en el XML.
        assert root.find(".//KOA210") is None
        assert b"KOA210" not in content
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_xtx_only_confirmed_tags_and_int_format(client: TestClient) -> None:
    """Validación de esquema: todo tag ABA/ABB emitido está en el set CONFIRMADO
    (research 10 / CAB oficial) — cero tags inventados — y los montos son enteros
    sin separadores de miles."""
    from app.services.forms import etax_schema_r7 as s

    draft = client.post("/api/v1/filing/draft?year=2025").json()
    content = client.get(f"/api/v1/filing/{draft['draft_id']}/xtx").content
    root = ET.fromstring(content)

    # Set de tags ABA/ABB confirmados (constantes TAG_*/GROUP del esquema).
    confirmed = {
        v for k, v in vars(s).items()
        if isinstance(v, str) and (v.startswith("ABA") or v.startswith("ABB"))
    }
    confirmed |= {s.HEADER_GROUP, s.BODY_GROUP}

    for el in root.iter():
        tag = el.tag
        if tag.startswith(("ABA", "ABB")):
            assert tag in confirmed, f"tag NO confirmado en el esquema: {tag}"
        # Montos: los tags ABB de cuerpo con texto numérico no llevan comas.
        if tag.startswith("ABB") and el.text and el.text.lstrip("-").isdigit() is False:
            assert "," not in el.text, f"monto con separador de miles: {tag}={el.text}"

    # Tags estructurales nuevos del 第一表 presentes (㊹基準, ㊻所得税等の額).
    assert root.find(".//ABB01010") is not None  # 基準所得税額.
    assert root.find(".//ABB01030") is not None  # 所得税及び復興特別所得税の額.


# --- CSV (SHIFT-JIS) ------------------------------------------------------


def test_csv_is_shift_jis(client: TestClient) -> None:
    """El CSV del 決算書 decodifica en SHIFT-JIS y trae los kanji de seccion."""
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    resp = client.get(f"/api/v1/filing/{draft['draft_id']}/csv")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert "shift_jis" in resp.headers["content-type"]
    text = resp.content.decode("shift_jis")
    assert "損益計算書" in text
    assert "貸借対照表" in text
    # No debe decodificar como UTF-8 si tiene kanji (asegura que es SHIFT-JIS real).
    with pytest.raises(UnicodeDecodeError):
        resp.content.decode("utf-8")


def test_official_package_zip_contains_verified_documents(client: TestClient) -> None:
    """El ZIP oficial incluye PDFs oficiales, libros, e-Tax/CSV y manifiesto OK."""
    draft = client.post("/api/v1/filing/draft?year=2025").json()
    resp = client.get(f"/api/v1/filing/{draft['draft_id']}/official-package")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        names = set(archive.namelist())
        assert {
            "00_manifest.json",
            "01_shinkokusho_official.pdf",
            "02_kessansho_official.pdf",
            "03_shiwakecho.pdf",
            "04_motocho.pdf",
            "05_shinkoku_2025.xtx",
            "06_kessansho_2025.csv",
        }.issubset(names)

        manifest = json.loads(archive.read("00_manifest.json").decode("utf-8"))
        assert manifest["checks"]["xtx_validation"]["ok"] is True
        assert manifest["checks"]["xtx_validation"]["errors"] == 0
        assert manifest["basis"]["etax"] == "KOA020 VR 23.0 + 決算書 CSV（SHIFT-JIS）"
        assert any("2・3ページは未記入" in note for note in manifest["notes"])
        assert any("受付" in note for note in manifest["notes"])

        for pdf_name in (
            "01_shinkokusho_official.pdf",
            "02_kessansho_official.pdf",
            "03_shiwakecho.pdf",
            "04_motocho.pdf",
        ):
            assert archive.read(pdf_name).startswith(b"%PDF-")

        ET.fromstring(archive.read("05_shinkoku_2025.xtx"))
        assert "損益計算書" in archive.read("06_kessansho_2025.csv").decode("shift_jis")


# --- Servicio puro --------------------------------------------------------


def test_build_filing_draft_balance_sheet(session: Session) -> None:
    """El 貸借対照表 del draft cuadra (資産 = 負債 + 資本 + 所得)."""
    result = build_filing_draft(session, 2025)
    bs = result.balance_sheet
    assert bs.is_balanced
    assert bs.total_assets == bs.total_liabilities + bs.total_equity + bs.net_income


def test_build_filing_draft_idempotent(session: Session) -> None:
    """Regenerar el draft no duplica asientos (mismo PL en dos corridas)."""
    first = build_filing_draft(session, 2025)
    second = build_filing_draft(session, 2025)
    assert first.income_statement.net_income == second.income_statement.net_income
    assert first.business_income == second.business_income


def test_pdf_render_contains_pdf_bytes(session: Session) -> None:
    """Los renderizadores de servicio producen PDF con la cabecera magic."""
    from app.services.forms.kessansho import render_kessansho_pdf
    from app.services.forms.shinkokusho import render_shinkokusho_pdf

    result = build_filing_draft(session, 2025)
    for content in (render_shinkokusho_pdf(result), render_kessansho_pdf(result)):
        assert io.BytesIO(content).read(5) == b"%PDF-"


def test_official_overlays_render_pdf(session: Session) -> None:
    """Los overlays oficiales (申告書 第一表二表, 青色決算書 P1+P4, 収支内訳書, .xtx)
    generan PDF/XML válidos sobre el 様式 oficial del NTA."""
    import fitz

    from app.services.forms.kessansho_official import render_kessansho_official
    from app.services.forms.shinkokusho_official import render_shinkokusho_official
    from app.services.forms.shushi_official import render_shushi_official

    result = build_filing_draft(session, 2025)
    sk = render_shinkokusho_official(result)
    ke = render_kessansho_official(result)
    su = render_shushi_official(result)
    for content in (sk, ke, su):
        assert io.BytesIO(content).read(5) == b"%PDF-"
    assert fitz.open(stream=sk, filetype="pdf").page_count == 2  # 第一表 + 第二表.
    assert fitz.open(stream=ke, filetype="pdf").page_count == 4  # P2/P3 sin rellenar.
    assert fitz.open(stream=su, filetype="pdf").page_count == 2  # P2 sin rellenar.
