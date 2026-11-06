"""Casos R7 de NTA 1140 y 1145; límites y fracciones de yen."""

import pytest

from app.services.forms.xtx_insurance import (
    InsurancePayment,
    insurance_deductions,
    new_contract,
    old_contract,
)


@pytest.mark.parametrize(("paid", "new", "old"), [
    (0, 0, 0), (20_000, 20_000, 20_000), (20_001, 20_001, 20_001),
    (25_000, 22_500, 25_000), (25_001, 22_501, 25_001),
    (40_000, 30_000, 32_500), (40_001, 30_001, 32_501),
    (50_000, 32_500, 37_500), (50_001, 32_501, 37_501),
    (80_000, 40_000, 45_000), (100_001, 40_000, 50_000),
])
def test_r7_life_brackets(paid: int, new: int, old: int) -> None:
    assert new_contract(paid) == new
    assert old_contract(paid) == old


def test_combined_old_new_selects_old_when_better_and_global_cap() -> None:
    rows = tuple(InsurancePayment(category, 200_000, 0) for category in (
        "new_life", "old_life", "new_pension", "old_pension", "care",
    ))
    assert insurance_deductions(rows) == (120_000, 0)
    assert insurance_deductions((InsurancePayment("old_life", 100_000, 0),
                                 InsurancePayment("new_life", 100_000, 0))) == (50_000, 0)


@pytest.mark.parametrize(("old", "expected"), [
    (0, 0), (10_000, 10_000), (10_001, 10_001), (20_000, 15_000), (20_001, 15_000),
])
def test_eligible_old_damage_contract(old: int, expected: int) -> None:
    assert insurance_deductions((InsurancePayment("old_damage", old, 0),)) == (0, expected)
    assert insurance_deductions((InsurancePayment("old_damage", old, 0),
                                 InsurancePayment("earthquake", 60_000, 0))) == (0, 50_000)


def test_outside_year_end_cannot_exceed_payment() -> None:
    with pytest.raises(ValueError):
        insurance_deductions((InsurancePayment("care", 1, 2),))
