"""Tests de los modelos del dominio: persistencia y relaciones."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    AuditLog,
    Deduction,
    Evidence,
    FilingDraft,
    FiscalYear,
    FixedAsset,
    IncomeSource,
    JournalEntry,
    JournalLine,
    Taxpayer,
    Transaction,
)
from app.models.enums import (
    AccountCategory,
    DeductionType,
    DepreciationMethod,
    FilingType,
    FiscalYearStatus,
    IncomeType,
    JournalSide,
    TransactionSource,
    TransactionStatus,
)


def _make_taxpayer(session: Session) -> Taxpayer:
    """Crea y persiste un Taxpayer minimo."""
    tp = Taxpayer(
        name="山田 太郎",
        name_kana="ヤマダ タロウ",
        my_number="123456789012",
        filing_type=FilingType.AOIRO_65,
        is_taxable_consumption=False,
    )
    session.add(tp)
    session.commit()
    return tp


def _make_fiscal_year(session: Session, taxpayer: Taxpayer) -> FiscalYear:
    """Crea y persiste un FiscalYear ligado al taxpayer."""
    fy = FiscalYear(
        taxpayer_id=taxpayer.id,
        year=2025,
        rules_ref="tax_rules/2025.json",
        status=FiscalYearStatus.OPEN,
    )
    session.add(fy)
    session.commit()
    return fy


def test_taxpayer_persist_and_uuid_pk(session: Session) -> None:
    """Taxpayer se persiste con PK uuid generada."""
    tp = _make_taxpayer(session)
    assert isinstance(tp.id, uuid.UUID)
    fetched = session.get(Taxpayer, tp.id)
    assert fetched is not None
    assert fetched.name == "山田 太郎"


def test_taxpayer_repr_hides_my_number(session: Session) -> None:
    """El repr de Taxpayer no expone el my_number (dato sensible)."""
    tp = _make_taxpayer(session)
    assert "123456789012" not in repr(tp)


def test_taxpayer_fiscal_year_relationship(session: Session) -> None:
    """Relacion Taxpayer 1-* FiscalYear navegable en ambos sentidos."""
    tp = _make_taxpayer(session)
    fy = _make_fiscal_year(session, tp)
    session.refresh(tp)
    assert len(tp.fiscal_years) == 1
    assert tp.fiscal_years[0].id == fy.id
    assert fy.taxpayer.id == tp.id


def test_account_persist(session: Session) -> None:
    """Account se persiste con su categoria enum."""
    acc = Account(code="401", name="売上高", category=AccountCategory.REVENUE)
    session.add(acc)
    session.commit()
    fetched = session.get(Account, acc.id)
    assert fetched is not None
    assert fetched.category == AccountCategory.REVENUE
    assert fetched.is_default is True


def test_evidence_and_transaction_relationship(session: Session) -> None:
    """Transaction 0..1-1 Evidence: el FK evidence_id enlaza correctamente."""
    tp = _make_taxpayer(session)
    fy = _make_fiscal_year(session, tp)
    ev = Evidence(file_ref="/receipts/001.jpg", hash="abc123", idx_vendor="JR東日本")
    session.add(ev)
    session.commit()

    tx = Transaction(
        fiscal_year_id=fy.id,
        date=date(2025, 4, 1),
        vendor="JR東日本",
        total_amount=1320,
        source=TransactionSource.OCR,
        evidence_id=ev.id,
        status=TransactionStatus.PENDING,
        tax_lines=[{"rate": 10, "base": 1200, "tax": 120}],
    )
    session.add(tx)
    session.commit()

    fetched = session.get(Transaction, tx.id)
    assert fetched is not None
    assert fetched.evidence is not None
    assert fetched.evidence.id == ev.id
    assert fetched.tax_lines == [{"rate": 10, "base": 1200, "tax": 120}]


def test_journal_entry_with_lines(session: Session) -> None:
    """JournalEntry con JournalLines (借方/貸方) y cascade de borrado."""
    tp = _make_taxpayer(session)
    fy = _make_fiscal_year(session, tp)
    cash = Account(code="101", name="現金", category=AccountCategory.ASSET)
    sales = Account(code="401", name="売上高", category=AccountCategory.REVENUE)
    session.add_all([cash, sales])
    session.commit()

    entry = JournalEntry(
        fiscal_year_id=fy.id,
        date=date(2025, 5, 10),
        description="現金売上",
        lines=[
            JournalLine(side=JournalSide.DEBIT, account_id=cash.id, amount=10000),
            JournalLine(side=JournalSide.CREDIT, account_id=sales.id, amount=10000),
        ],
    )
    session.add(entry)
    session.commit()

    fetched = session.get(JournalEntry, entry.id)
    assert fetched is not None
    assert len(fetched.lines) == 2

    # Cascade: borrar el entry borra sus lineas.
    session.delete(fetched)
    session.commit()
    assert session.scalar(select(JournalLine).limit(1)) is None


def test_deduction_income_fixed_asset_filing_audit(session: Session) -> None:
    """Persistencia de Deduction, IncomeSource, FixedAsset, FilingDraft, AuditLog."""
    tp = _make_taxpayer(session)
    fy = _make_fiscal_year(session, tp)

    ded = Deduction(
        fiscal_year_id=fy.id,
        type=DeductionType.IRYOHI,
        amount=120000,
        meta={"hospital": "X病院"},
    )
    inc = IncomeSource(
        fiscal_year_id=fy.id,
        income_type=IncomeType.KYUYO,
        gross=3000000,
        withholding=80000,
    )
    asset = FixedAsset(
        fiscal_year_id=fy.id,
        name="ノートPC",
        acquisition_date=date(2025, 1, 15),
        cost=300000,
        method=DepreciationMethod.TEIGAKU,
        useful_life=4,
    )
    draft = FilingDraft(fiscal_year_id=fy.id, computed={"income_tax": 12345})
    log = AuditLog(
        entity="transaction",
        entity_id=str(uuid.uuid4()),
        action="create",
        after={"total_amount": 1000},
    )
    session.add_all([ded, inc, asset, draft, log])
    session.commit()

    session.refresh(fy)
    assert len(fy.deductions) == 1
    assert len(fy.income_sources) == 1
    assert len(fy.filing_drafts) == 1
    assert session.get(FixedAsset, asset.id) is not None
    assert session.get(AuditLog, log.id) is not None
    assert fy.deductions[0].meta == {"hospital": "X病院"}
