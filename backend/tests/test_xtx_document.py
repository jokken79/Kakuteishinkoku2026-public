"""Contratos fiscales y estructurales del generador R7 con datos sintéticos."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET  # nosec B405
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.models.entities import Transaction
from app.models.enums import TransactionStatus
from app.seed.dev_seed import seed_demo_data
from app.services.forms.drafting import FilingDraftResult, build_filing_draft
from app.services.forms.etax_export import build_xtx
from app.services.forms.etax_validator import validate_xtx_against_xsd
from app.services.forms.xtx_catalog import emit_fields
from app.services.forms.xtx_document import (
    PayerIncome,
    PremiumPayment,
    XtxDetails,
    build_xtx_document,
)
from app.services.forms.xtx_envelope import SHOTOKU, XtxIdentity


@pytest.fixture
def synthetic_draft(session: Session) -> FilingDraftResult:
    seed_demo_data(session)
    for tx in session.query(Transaction).all():
        tx.status = TransactionStatus.CONFIRMED
    session.commit()
    return build_filing_draft(session, 2025)


def identity(draft: FilingDraftResult) -> XtxIdentity:
    assert draft.taxpayer_profile is not None
    assert draft.taxpayer_profile.address is not None
    return XtxIdentity(
        "0000000000000000",
        draft.taxpayer_name,
        draft.taxpayer_profile.address,
        "06127",
        "000000000000",
        date(1980, 1, 1),
    )


def details(draft: FilingDraftResult) -> XtxDetails:
    db = draft.tax.deduction_breakdown
    return XtxDetails(
        payers=(
            PayerIncome(
                "jigyo",
                "Synthetic Customer",
                "Synthetic Address",
                draft.sales_revenue,
                draft.tax.withholding_tax,
            ),
        ),
        monthly_sales=(draft.sales_revenue, *([0] * 11)),
        opening_balances={},
        business_period=(date(2025, 1, 1), date(2025, 12, 31)),
        premiums=(
            PremiumPayment("social", "社会保険料", db.social_insurance, db.social_insurance),
            PremiumPayment("ideco", "個人型確定拠出年金", db.ideco, db.ideco),
        ),
    )


def test_generator_requires_explicit_identity(synthetic_draft: FilingDraftResult) -> None:
    with pytest.raises(ValueError, match="identidad"):
        build_xtx(synthetic_draft)


def test_generation_preserves_income_and_reconciles_fiscal_balance(
    synthetic_draft: FilingDraftResult,
) -> None:
    draft = synthetic_draft
    result = build_xtx_document(
        draft, identity(draft), created_on=date(2026, 1, 1), details=details(draft)
    )
    # El importador oficial rechazó ns0:DATA y admitió el namespace por defecto.
    assert b'<DATA xmlns="http://xml.e-tax.nta.go.jp/XSD/shotoku"' in result.xml
    assert b'xmlns:gen="http://xml.e-tax.nta.go.jp/XSD/general"' in result.xml
    assert b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"' in result.xml
    root = ET.fromstring(result.xml)
    assert root.findtext(".//{*}ABB00030") == str(draft.sales_revenue)
    assert root.findtext(".//{*}AMF00530") == str(draft.business_income)
    assert root.findtext(".//{*}AMG00440") == root.findtext(".//{*}AMG00760")
    assert root.findtext(".//{*}AMG00430") == str(draft.sales_revenue)
    assert root.findtext(".//{*}AMG00230") == "0"
    assert root.findtext(".//{*}AMG00610") == "0"
    assert {el.tag.split("}")[-1] for el in root.findall(".//{*}KOA210/*")} == {
        "KOA210-1",
        "KOA210-2",
        "KOA210-3",
        "KOA210-4",
    }
    assert result.missing == ("official_import_acceptance",)
    assert not result.ready_for_submission


def test_unknown_expenses_keep_names_in_additional_rows(synthetic_draft: FilingDraftResult) -> None:
    draft = synthetic_draft
    root = ET.fromstring(build_xtx(draft, identity=identity(draft), details=details(draft)))
    names = [el.text for el in root.findall(".//{*}AMF00355/{*}AMF00060")]
    assert "支払手数料" in names
    rows = root.findall(".//{*}AMF00355")
    total = sum(int(row.findtext("{*}AMF00360", "0")) for row in rows)
    expected = sum(
        line.amount for line in draft.income_statement.expenses if line.account_name in names
    )
    assert total == expected


def test_missing_sources_are_reported_without_fabrication(
    synthetic_draft: FilingDraftResult,
) -> None:
    draft = synthetic_draft
    result = build_xtx_document(draft, identity(draft), created_on=date(2026, 1, 1))
    assert {
        "income_payers",
        "monthly_sales",
        "opening_balances",
        "premium_reconciliation:social",
        "premium_reconciliation:ideco",
    }.issubset(result.missing)
    assert not ET.fromstring(result.xml).findall(".//{*}ABD00010")


def test_monthly_sales_must_reconcile(synthetic_draft: FilingDraftResult) -> None:
    with pytest.raises(ValueError, match="mensual"):
        build_xtx_document(
            synthetic_draft,
            identity(synthetic_draft),
            created_on=date(2026, 1, 1),
            details=XtxDetails(monthly_sales=(1,) * 12),
        )


def test_payers_continue_on_second_page_without_duplicate_withholding(
    synthetic_draft: FilingDraftResult,
) -> None:
    draft = synthetic_draft
    payers = tuple(PayerIncome("jigyo", f"Synthetic {i}", "Example", 100, 10) for i in range(5))
    result = build_xtx_document(
        draft, identity(draft), created_on=date(2026, 1, 1), details=XtxDetails(payers=payers)
    )
    root = ET.fromstring(result.xml)
    assert len(root.findall(".//{*}KOA020-2")) == 2
    assert len(root.findall(".//{*}ABD00010")) == 5
    assert [el.text for el in root.findall(".//{*}ABD00070")] == ["50"]
    assert "payer_gross_reconciliation:jigyo" in result.missing
    assert "payer_withholding_reconciliation" in result.missing


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValueError, match="correspondencia"):
        emit_fields(ET.Element(f"{{{SHOTOKU}}}KOA020-1"), "KOA020-1", {"ABB99999": 100})


def test_official_xsd_and_rdf_negative_cases(synthetic_draft: FilingDraftResult) -> None:
    path = os.environ.get("ETAX_OFFICIAL_XSD")
    if not path:
        pytest.skip("Requiere árbol oficial local y ETAX_OFFICIAL_XSD.")
    pytest.importorskip("lxml")
    draft = synthetic_draft
    content = build_xtx(draft, identity=identity(draft), details=details(draft))
    report = validate_xtx_against_xsd(content, Path(path))
    assert report.ok, report.as_dict()
    broken = content.replace(b'about="#KOA210-1"', b'about="#missing"')
    report = validate_xtx_against_xsd(broken, Path(path))
    assert not report.ok
    assert "unresolved_reference" in {issue.code for issue in report.issues}
    # El XSD por sí solo permite un catálogo RDF vacío; la validación adicional lo rechaza.
    root = ET.fromstring(content)
    catalog = root.find(".//{*}CATALOG")
    assert catalog is not None
    catalog.clear()
    catalog.set("id", "CATALOG")
    ET.SubElement(catalog, "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF")
    report = validate_xtx_against_xsd(ET.tostring(root), Path(path))
    assert not report.ok
    assert "missing_rdf_catalog" in {issue.code for issue in report.issues}


def test_masked_my_number_is_rejected(synthetic_draft: FilingDraftResult) -> None:
    draft = synthetic_draft
    valid = identity(draft)
    masked = XtxIdentity(
        valid.user_id, valid.name, valid.address, valid.office_code, "********0000"
    )
    with pytest.raises(ValueError, match="doce"):
        build_xtx_document(draft, masked, created_on=date(2026, 1, 1))


def test_year_2026_is_not_exported_with_2025_schema(synthetic_draft: FilingDraftResult) -> None:
    draft = synthetic_draft
    draft.year = 2026
    with pytest.raises(ValueError, match="2025"):
        build_xtx_document(draft, identity(draft), created_on=date(2026, 11, 5))


def test_xsd_rejects_entities_before_schema_loading() -> None:
    payload = b'<!DOCTYPE DATA [<!ENTITY x "secret">]><DATA>&x;</DATA>'
    report = validate_xtx_against_xsd(payload, Path("RKO0010-250.xsd"))
    assert not report.ok
    assert {issue.code for issue in report.issues} == {"unsafe_xml"}


def test_tax_credit_total_is_not_guessed_to_be_housing(synthetic_draft: FilingDraftResult) -> None:
    draft = synthetic_draft
    draft.tax.tax_credits = 40_000
    result = build_xtx_document(draft, identity(draft), created_on=date(2026, 1, 1))
    assert ET.fromstring(result.xml).find(".//{*}ABB00650") is None
    assert "tax_credit_allocation" in result.missing


def test_multiple_salary_items_are_summed_in_the_same_box(
    synthetic_draft: FilingDraftResult,
) -> None:
    from app.domain.tax.schemas import IncomeBreakdownItem, IncomeKind

    draft = synthetic_draft
    draft.tax.income_breakdown = [
        IncomeBreakdownItem(kind=IncomeKind.KYUYO, amount=100_000, label="Synthetic A"),
        IncomeBreakdownItem(kind=IncomeKind.KYUYO, amount=200_000, label="Synthetic B"),
    ]
    root = ET.fromstring(build_xtx(draft, identity=identity(draft)))
    assert root.findtext(".//{*}ABB00370") == "300000"


def test_tax_office_must_match_the_profile(synthetic_draft: FilingDraftResult) -> None:
    draft = synthetic_draft
    valid = identity(draft)
    other = XtxIdentity(valid.user_id, valid.name, valid.address, "01143")
    with pytest.raises(ValueError, match="oficina"):
        build_xtx_document(draft, other, created_on=date(2026, 1, 1))
