"""Pruebas con importes sintéticos de 住民税."""

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


def test_synthetic_resident_tax_with_and_without_dependent() -> None:
    rules = load_tax_rules(2025)
    def compute(dependents: list[Dependent]):
        national = calculate(TaxCalculationInput(
            year=2025, incomes=[IncomeInput(kind=IncomeKind.JIGYO, amount=3_000_000)],
            deductions=DeductionInput(social_insurance=700_000, dependents=dependents),
        ), rules)
        return calculate_resident_tax(national, dependents, rules)
    basic = compute([])
    dependent = compute([Dependent(kind=DependentKind.ELDERLY)])
    assert basic.kiso_kojo == 430_000
    assert basic.taxable_income == 1_870_000
    assert basic.shotokuwari_total == 187_000
    assert basic.kintowari_total == 5_500
    assert basic.chosei_kojo == 2_500
    assert basic.total == 190_000
    assert dependent.dependent_deduction == 380_000
    assert dependent.taxable_income == 1_490_000
    assert dependent.chosei_kojo == 7_500
    assert dependent.total == 147_000
