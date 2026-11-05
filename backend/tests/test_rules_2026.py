"""Casos 2026 contrastados con los tramos publicados por 国税庁."""

import pytest
from fastapi import HTTPException

from app.api.filing import _require_verified_export
from app.domain.tax.income import salary_income
from app.domain.tax.income_tax import calculate
from app.domain.tax.resident_tax import calculate_resident_tax
from app.domain.tax.schemas import (
    DeductionInput,
    Dependent,
    DependentKind,
    IncomeInput,
    IncomeKind,
    TaxCalculationInput,
)
from app.services.tax_rules import load_tax_rules


@pytest.mark.parametrize(
    ("salary", "income"),
    [(740_999, 0), (741_000, 1_000), (2_190_999, 1_450_999),
     (2_191_000, 1_451_000), (2_192_999, 1_451_000),
     (2_193_000, 1_453_000), (2_195_999, 1_453_000),
     (2_196_000, 1_456_000), (2_199_999, 1_456_000),
     (2_200_000, 1_460_000), (5_000_000, 3_560_000)],
)
def test_2026_salary_special_table(salary: int, income: int) -> None:
    assert salary_income(salary, load_tax_rules(2026)) == income


@pytest.mark.parametrize(
    ("income", "deduction"),
    [(0, 1_040_000), (1_320_000, 1_040_000), (1_320_001, 1_040_000),
     (3_360_000, 1_040_000), (3_360_001, 1_040_000), (4_890_000, 1_040_000),
     (4_890_001, 670_000), (6_550_000, 670_000), (6_550_001, 620_000),
     (23_500_001, 480_000), (24_000_001, 320_000),
     (24_500_001, 160_000), (25_000_001, 0)],
)
def test_2026_basic_deduction_boundaries(income: int, deduction: int) -> None:
    assert load_tax_rules(2026).kiso_kojo_for(income) == deduction


def test_2026_salary_mother_and_disability_estimate() -> None:
    result = calculate(TaxCalculationInput(
        year=2026,
        incomes=[IncomeInput(kind=IncomeKind.KYUYO, revenue=5_000_000)],
        deductions=DeductionInput(
            social_insurance=700_000,
            disability_deduction=270_000,
            dependents=[Dependent(kind=DependentKind.ELDERLY)],
        ),
    ))
    assert result.total_income == 3_560_000
    assert result.taxable_income == 1_070_000
    assert result.total_tax == 54_623
    assert result.final_amount == 54_600


def test_unverified_official_export_is_blocked() -> None:
    _require_verified_export(2025)
    with pytest.raises(HTTPException) as error:
        _require_verified_export(2026)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "filing_format_not_verified"


def test_self_disability_is_distinct_for_resident_tax() -> None:
    deps = [Dependent(kind=DependentKind.ELDERLY)]
    national = calculate(TaxCalculationInput(
        year=2026,
        incomes=[IncomeInput(kind=IncomeKind.KYUYO, revenue=5_000_000)],
        deductions=DeductionInput(
            social_insurance=700_000, ordinary_disability_self=True, dependents=deps,
        ),
    ))
    resident = calculate_resident_tax(national, deps, load_tax_rules(2026))
    assert national.deduction_breakdown.other == 270_000
    assert national.total_tax == 54_623
    assert resident.taxable_income == 1_790_000
    assert resident.chosei_kojo == 8_000
    assert resident.total == 176_500
