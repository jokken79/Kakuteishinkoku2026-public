"""Tests del loader de parametros fiscales (`app.services.tax_rules`)."""

import pytest

from app.services.tax_rules import TaxRules, load_tax_rules


def test_load_2025_parses_and_validates() -> None:
    """El JSON de 2025 carga y valida como `TaxRules`."""
    rules = load_tax_rules(2025)
    assert isinstance(rules, TaxRules)
    assert rules.year == 2025
    assert rules.era == "令和7"
    assert rules.reconstruction_tax_rate == 0.021
    assert rules.salary_deduction_min == 650_000
    assert rules.dependent_income_threshold == 580_000


def test_load_is_cached() -> None:
    """Cargar el mismo anio dos veces devuelve la misma instancia (cache)."""
    a = load_tax_rules(2025)
    b = load_tax_rules(2025)
    assert a is b


def test_load_missing_year_raises() -> None:
    """Un anio sin JSON levanta FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_tax_rules(1999)


@pytest.mark.parametrize(
    ("total_income", "expected"),
    [
        (1_000_000, 950_000),  # tramo <= 1,320,000
        (1_320_000, 950_000),  # borde inclusivo
        (2_000_000, 880_000),  # 1,320,000 - 3,360,000 (temporal)
        (4_000_000, 680_000),  # 3,360,000 - 4,890,000 (temporal)
        (5_000_000, 630_000),  # 4,890,000 - 6,550,000 (temporal)
        (10_000_000, 580_000),  # 6,550,000 - 23,500,000
        (23_800_000, 480_000),  # 23,500,000 - 24,000,000
        (24_300_000, 320_000),  # 24,000,000 - 24,500,000
        (24_800_000, 160_000),  # 24,500,000 - 25,000,000
        (30_000_000, 0),  # > 25,000,000
    ],
)
def test_kiso_kojo_escalonado(total_income: int, expected: int) -> None:
    """La tabla escalonada de 基礎控除 令和7 devuelve el monto correcto por tramo."""
    rules = load_tax_rules(2025)
    assert rules.kiso_kojo_for(total_income) == expected


def test_bracket_for_returns_correct_tramo() -> None:
    """`bracket_for` selecciona el tramo correcto del 速算表."""
    rules = load_tax_rules(2025)
    assert rules.bracket_for(1_000_000).rate == 0.05
    assert rules.bracket_for(3_000_000).rate == 0.10
    assert rules.bracket_for(5_000_000).rate == 0.20
    assert rules.bracket_for(8_000_000).rate == 0.23
    assert rules.bracket_for(15_000_000).rate == 0.33
    assert rules.bracket_for(30_000_000).rate == 0.40
    assert rules.bracket_for(50_000_000).rate == 0.45
