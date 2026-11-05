"""Ejemplo sintético para desarrollo."""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_engine, get_session_factory
from app.models import Base
from app.models.entities import (
    Deduction,
    Evidence,
    FiscalYear,
    IncomeSource,
    Taxpayer,
    Transaction,
)
from app.models.enums import (
    DeductionType,
    FilingType,
    FiscalYearStatus,
    IncomeType,
    TransactionSource,
    TransactionStatus,
)
from app.seed.accounts import seed_accounts
from app.seed.vendor_mapping import classify_vendor

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)










SYNTHETIC_SALARY_GROSS = 5_200_000
SYNTHETIC_SALARY_WITHHOLDING = 100_000





SYNTHETIC_BUSINESS_SALES = 100_000



SYNTHETIC_EXPENSES: tuple[tuple[date, str, str, int], ...] = (

    (date(2025, 2, 28), "502", "消耗品費", 180_000),
    (date(2025, 9, 30), "509", "広告宣伝費", 110_000),
    (date(2025, 1, 31), "511", "租税公課", 90_000),
    (date(2025, 12, 31), "514", "損害保険料", 50_000),
    (date(2025, 6, 30), "505", "通信費", 20_000),
    (date(2025, 7, 25), "510", "支払手数料", 10_000),
    (date(2025, 4, 10), "501", "旅費交通費", 1_000),
)







SYNTHETIC_SOCIAL_INSURANCE = 700_000



SYNTHETIC_HOUSING_LOAN_CLAIM = 40_000






DEMO_SALES_REVENUE = 6_800_000
DEMO_WITHHOLDING_TAX = 410_000
DEMO_SOCIAL_INSURANCE = 300_000
DEMO_IDECO = 276_000


@dataclass(frozen=True)
class ReceiptSeed:
    """Ejemplo sintético para desarrollo."""

    day: date
    vendor: str
    total: int
    rate: int
    confidence: float
    registration_number: str | None = None
    is_qualified: bool = False


def _field_confidences(confidence: float, *, has_reg: bool) -> dict[str, float]:
    """Ejemplo sintético para desarrollo."""
    base = confidence
    fields = {
        "date": min(1.0, round(base + 0.06, 4)),
        "vendor": round(base, 4),
        "total": round(base, 4),
        "tax_lines": min(1.0, round(base + 0.04, 4)),
        "registration_number": (round(base, 4) if has_reg else 0.0),
    }
    if confidence < 0.75:

        weakest = "total" if confidence < 0.6 else "vendor"
        fields[weakest] = round(confidence - 0.12, 4)
    return fields


def _tax_lines(total: int, rate: int) -> list[dict[str, Any]]:
    """Ejemplo sintético para desarrollo."""
    base = round(total / (1 + rate / 100))
    tax = total - base
    return [{"base": base, "tax": tax, "rate": rate}]



RECEIPTS: tuple[ReceiptSeed, ...] = (
    ReceiptSeed(
        date(2025, 1, 15), "東日本旅客鉄道（JR東日本）", 13640, 10, 0.94,
        "T1010001000001", True,
    ),
    ReceiptSeed(
        date(2025, 2, 3), "株式会社NTTドコモ", 8778, 10, 0.91,
        "T2020002000002", True,
    ),
    ReceiptSeed(date(2025, 2, 18), "Amazon.co.jp", 4980, 10, 0.88),
    ReceiptSeed(date(2025, 3, 7), "スターバックス コーヒー 渋谷店", 1320, 10, 0.52),
    ReceiptSeed(
        date(2025, 4, 22), "ヨドバシカメラ", 21780, 10, 0.83,
        "T3030003000003", True,
    ),
    ReceiptSeed(date(2025, 5, 9), "セブン-イレブン 新宿三丁目店", 2160, 8, 0.61),
    ReceiptSeed(date(2025, 6, 2), "さくらインターネット株式会社", 5500, 10, 0.96),
    ReceiptSeed(date(2025, 6, 14), "居酒屋 とり鉄 池袋店", 8800, 10, 0.47),
    ReceiptSeed(date(2025, 7, 1), "Apple Store", 198000, 10, 0.79),
    ReceiptSeed(date(2025, 8, 20), "紀伊國屋書店 新宿本店", 3740, 10, 0.68),


    ReceiptSeed(date(2025, 9, 12), "ウエルシア薬局 新宿店", 12800, 10, 0.86),
    ReceiptSeed(date(2025, 10, 5), "さとふる（ふるさと納税）", 50000, 10, 0.9),
)


def _normalize_deduction_type(raw: object) -> DeductionType | None:
    """Ejemplo sintético para desarrollo."""
    if isinstance(raw, DeductionType):
        return raw
    try:
        return DeductionType(cast(str, getattr(raw, "value", raw)))
    except ValueError:
        return None


def _get_or_create_fiscal_year(session: Session, taxpayer: Taxpayer) -> tuple[FiscalYear, int]:
    """Ejemplo sintético para desarrollo."""
    fy = session.scalars(
        select(FiscalYear).where(
            FiscalYear.taxpayer_id == taxpayer.id, FiscalYear.year == 2025
        )
    ).first()
    if fy is not None:
        return fy, 0
    fy = FiscalYear(
        taxpayer_id=taxpayer.id,
        year=2025,
        rules_ref="2025",
        status=FiscalYearStatus.OPEN,
    )
    session.add(fy)
    session.flush()
    return fy, 1


def seed_dev_data(session: Session, *, commit: bool = True) -> dict[str, int]:
    """Ejemplo sintético para desarrollo."""
    counts = {
        "taxpayers": 0,
        "fiscal_years": 0,
        "transactions": 0,
        "income_sources": 0,
        "deductions": 0,
    }

    seed_accounts(session, commit=False)


    taxpayer = session.scalars(
        select(Taxpayer).where(Taxpayer.name == "架空 太郎")
    ).first()
    if taxpayer is None:
        taxpayer = Taxpayer(
            name="架空 太郎",
            name_kana="カクウ タロウ",
            my_number=None,

            postal_code="000-0000",
            address="架空県架空市1-1",
            birth_date=date(1985, 1, 1),
            filing_type=FilingType.AOIRO_65,
            is_taxable_consumption=False,
            business_type="会社員（派遣）",
            filing_office="tsushima",
            onboarded=True,
        )
        session.add(taxpayer)
        session.flush()
        counts["taxpayers"] += 1
    else:
        if not taxpayer.onboarded:
            taxpayer.onboarded = True
        if taxpayer.filing_office is None:
            taxpayer.filing_office = "tsushima"

    fy, fy_created = _get_or_create_fiscal_year(session, taxpayer)
    counts["fiscal_years"] += fy_created


    existing = {
        (t.vendor, t.date, t.total_amount)
        for t in session.scalars(
            select(Transaction).where(Transaction.fiscal_year_id == fy.id)
        ).all()
    }
    for day, code, label, total in SYNTHETIC_EXPENSES:
        key = (label, day, total)
        if key in existing:
            continue
        retention = date(day.year + 7, day.month, 1)
        evidence = Evidence(
            file_ref=f"data/evidence/synthetic-{day.isoformat()}-{total}.bin",
            hash=f"synthetic{day.isoformat()}{total}",
            timestamp=_dt.datetime.now(_dt.UTC),
            idx_date=day,
            idx_amount=total,
            idx_vendor=label,
            retention_until=retention,
        )
        session.add(evidence)
        session.flush()

        tx = Transaction(
            fiscal_year_id=fy.id,
            date=day,
            vendor=label,
            total_amount=total,
            source=TransactionSource.MANUAL,
            evidence_id=evidence.id,
            registration_number=None,
            is_qualified_invoice=False,
            confidence=None,
            status=TransactionStatus.CONFIRMED,
            tax_lines=_tax_lines(total, 10),
            account_code=code,
            field_confidences=None,
        )
        session.add(tx)
        counts["transactions"] += 1



    existing_income = {
        s.income_type
        for s in session.scalars(
            select(IncomeSource).where(IncomeSource.fiscal_year_id == fy.id)
        ).all()
    }
    income_seed: tuple[tuple[IncomeType, int, int, dict[str, Any] | None], ...] = (
        (IncomeType.JIGYO, SYNTHETIC_BUSINESS_SALES, 0, {"label": "副業（事業所得）"}),
        (
            IncomeType.KYUYO,
            SYNTHETIC_SALARY_GROSS,
            SYNTHETIC_SALARY_WITHHOLDING,
            {"label": "給与（架空会社）"},
        ),
    )
    for income_type, gross, withholding, meta in income_seed:
        if income_type in existing_income:
            continue
        session.add(
            IncomeSource(
                fiscal_year_id=fy.id,
                income_type=income_type,
                gross=gross,
                withholding=withholding,
                meta=meta,
            )
        )
        counts["income_sources"] += 1




    deduction_rows = list(
        session.scalars(
            select(Deduction).where(Deduction.fiscal_year_id == fy.id)
        ).all()
    )
    existing_deductions = {
        _normalize_deduction_type(d.type): d for d in deduction_rows
    }



    deduction_seed: tuple[tuple[DeductionType, int, dict[str, Any] | None], ...] = (
        (
            DeductionType.SHAKAI_HOKEN,
            SYNTHETIC_SOCIAL_INSURANCE,
            {"label": "社会保険料控除（源泉徴収票）"},
        ),
        (
            DeductionType.HOUSING_LOAN,
            SYNTHETIC_HOUSING_LOAN_CLAIM,
            {
                "label": "住宅借入金等特別控除（居住開始 2025-01-01）",
                "tax_credit": True,
                "claim_status": "rejected",
                "rejection_reason": "not_accepted_by_tax_office",
            },
        ),
    )
    for ded_type, amount, meta in deduction_seed:
        existing_deduction = existing_deductions.get(ded_type)
        if existing_deduction is not None:
            if ded_type == DeductionType.HOUSING_LOAN:
                existing_meta = (
                    dict(existing_deduction.meta)
                    if isinstance(existing_deduction.meta, dict)
                    else {}
                )
                if "claim_status" not in existing_meta:
                    existing_deduction.meta = {
                        **existing_meta,
                        "claim_status": "rejected",
                        "rejection_reason": "not_accepted_by_tax_office",
                    }
            continue
        session.add(
            Deduction(
                fiscal_year_id=fy.id,
                type=ded_type,
                amount=amount,
                meta=meta,
            )
        )
        counts["deductions"] += 1

    if commit:
        session.commit()
    return counts


def seed_demo_data(session: Session, *, commit: bool = True) -> dict[str, int]:
    """Ejemplo sintético para desarrollo."""
    counts = {
        "taxpayers": 0,
        "fiscal_years": 0,
        "transactions": 0,
        "income_sources": 0,
        "deductions": 0,
    }

    seed_accounts(session, commit=False)

    taxpayer = session.scalars(
        select(Taxpayer).where(Taxpayer.name == "架空 花子")
    ).first()
    if taxpayer is None:
        taxpayer = Taxpayer(
            name="架空 花子",
            name_kana="カクウ ハナコ",
            postal_code="000-0000",
            address="架空県架空市2-2",
            birth_date=date(1986, 2, 2),
            filing_type=FilingType.AOIRO_65,
            is_taxable_consumption=False,
            business_type="ソフトウェア開発（ITフリーランス）",
            filing_office="tsushima",
            onboarded=True,
        )
        session.add(taxpayer)
        session.flush()
        counts["taxpayers"] += 1
    else:
        if not taxpayer.onboarded:
            taxpayer.onboarded = True
        if taxpayer.filing_office is None:
            taxpayer.filing_office = "tsushima"

    fy, fy_created = _get_or_create_fiscal_year(session, taxpayer)
    counts["fiscal_years"] += fy_created

    existing = {
        (t.vendor, t.date, t.total_amount)
        for t in session.scalars(
            select(Transaction).where(Transaction.fiscal_year_id == fy.id)
        ).all()
    }
    for r in RECEIPTS:
        key = (r.vendor, r.day, r.total)
        if key in existing:
            continue
        retention = date(r.day.year + 7, r.day.month, 1)
        evidence = Evidence(
            file_ref=f"data/evidence/demo-{r.day.isoformat()}-{r.total}.bin",
            hash=f"demo{r.day.isoformat()}{r.total}",
            timestamp=_dt.datetime.now(_dt.UTC),
            idx_date=r.day,
            idx_amount=r.total,
            idx_vendor=r.vendor,
            retention_until=retention,
        )
        session.add(evidence)
        session.flush()

        tx = Transaction(
            fiscal_year_id=fy.id,
            date=r.day,
            vendor=r.vendor,
            total_amount=r.total,
            source=TransactionSource.OCR,
            evidence_id=evidence.id,
            registration_number=r.registration_number,
            is_qualified_invoice=r.is_qualified,
            confidence=r.confidence,
            status=TransactionStatus.CONFIRMED,
            tax_lines=_tax_lines(r.total, r.rate),
            account_code=classify_vendor(r.vendor) or "599",
            field_confidences=_field_confidences(
                r.confidence, has_reg=r.registration_number is not None
            ),
        )
        session.add(tx)
        counts["transactions"] += 1

    existing_income = {
        s.income_type
        for s in session.scalars(
            select(IncomeSource).where(IncomeSource.fiscal_year_id == fy.id)
        ).all()
    }
    income_seed: tuple[tuple[IncomeType, int, int, dict[str, Any] | None], ...] = (
        (IncomeType.JIGYO, DEMO_SALES_REVENUE, 0, {"label": "ソフトウェア開発（報酬）"}),
        (IncomeType.KYUYO, 0, DEMO_WITHHOLDING_TAX, {"label": "給与所得の源泉徴収"}),
    )
    for income_type, gross, withholding, meta in income_seed:
        if income_type in existing_income:
            continue
        session.add(
            IncomeSource(
                fiscal_year_id=fy.id,
                income_type=income_type,
                gross=gross,
                withholding=withholding,
                meta=meta,
            )
        )
        counts["income_sources"] += 1

    existing_deductions = {
        _normalize_deduction_type(d.type)
        for d in session.scalars(
            select(Deduction).where(Deduction.fiscal_year_id == fy.id)
        ).all()
    }
    deduction_seed: tuple[tuple[DeductionType, int, dict[str, Any] | None], ...] = (
        (DeductionType.SHAKAI_HOKEN, DEMO_SOCIAL_INSURANCE, {"label": "国民年金・国民健康保険"}),
        (DeductionType.IDECO, DEMO_IDECO, {"label": "iDeCo（小規模企業共済等掛金）"}),
    )
    for ded_type, amount, meta in deduction_seed:
        if ded_type in existing_deductions:
            continue
        session.add(
            Deduction(
                fiscal_year_id=fy.id,
                type=ded_type,
                amount=amount,
                meta=meta,
            )
        )
        counts["deductions"] += 1

    if commit:
        session.commit()
    return counts


def main() -> None:
    """Ejemplo sintético para desarrollo."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        counts = seed_dev_data(session)
        logger.info(
            "Seed sintético: %d taxpayer(s), %d 年度, %d 仕訳, %d 収入, %d 控除.",
            counts["taxpayers"],
            counts["fiscal_years"],
            counts["transactions"],
            counts["income_sources"],
            counts["deductions"],
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
