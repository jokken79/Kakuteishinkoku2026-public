"""Tests del calculo de cada 所得 (`app.domain.tax.income`)."""

import pytest

from app.domain.tax.income import (
    business_income,
    compute_all_incomes,
    dividend_income,
    miscellaneous_income,
    real_estate_income,
    salary_income,
    temporary_income,
)
from app.domain.tax.income_tax import calculate
from app.domain.tax.schemas import (
    IncomeInput,
    IncomeKind,
    TaxCalculationInput,
    WithholdingInput,
)
from app.services.tax_rules import load_tax_rules


@pytest.fixture
def rules():
    """Parametros fiscales 2025."""
    return load_tax_rules(2025)


@pytest.mark.parametrize(
    ("revenue", "expected"),
    [
        # 収入 <= 1,800,000: 控除 = rev*0.4 - 100,000, pero con piso 650,000.
        # rev=1,000,000: 0.4*1M-100k = 300k < 650k -> usa 650k. 所得 = 350,000.
        (1_000_000, 350_000),
        # rev=1,800,000: 0.4*1.8M-100k = 620k < 650k -> piso 650k. 所得 = 1,150,000.
        (1_800_000, 1_150_000),
        # rev=2,000,000: tramo 30%+80k -> 控除 = 680,000. 所得 = 1,320,000.
        (2_000_000, 1_320_000),
        # rev=4,000,000: tramo 20%+440k -> 控除 = 1,240,000. 所得 = 2,760,000.
        (4_000_000, 2_760_000),
        # rev=7,000,000: tramo 10%+1.1M -> 控除 = 1,800,000. 所得 = 5,200,000.
        (7_000_000, 5_200_000),
        # rev=10,000,000: tope 控除 = 1,950,000. 所得 = 8,050,000.
        (10_000_000, 8_050_000),
        (0, 0),
    ],
)
def test_salary_income(revenue: int, expected: int, rules) -> None:
    """給与所得 = 収入 − 給与所得控除 (令和7, piso ¥650k)."""
    assert salary_income(revenue, rules) == expected


def test_business_income_passthrough() -> None:
    """事業所得 llega ya neto (PL − 青色特別控除); se pasa tal cual."""
    assert business_income(5_000_000) == 5_000_000
    assert business_income(-300_000) == -300_000  # perdida


def test_miscellaneous_income() -> None:
    """雑所得 = 収入 − 経費, no baja de 0."""
    assert miscellaneous_income(500_000, 100_000) == 400_000
    assert miscellaneous_income(100_000, 200_000) == 0


def test_real_estate_income_keeps_sign() -> None:
    """不動産所得 = 収入 − 経費 (respeta perdida)."""
    assert real_estate_income(1_000_000, 300_000) == 700_000
    assert real_estate_income(300_000, 500_000) == -200_000


@pytest.mark.parametrize(
    ("revenue", "expenses", "expected"),
    [
        # (収入 − 支出 − 500k) * 1/2.
        (1_500_000, 0, 500_000),  # (1.5M - 500k)/2 = 500k
        (800_000, 100_000, 100_000),  # (800k-100k-500k)/2 = 100k
        (400_000, 0, 0),  # neto negativo -> 0
        (700_001, 0, 100_000),  # (700,001-500,000)//2 = 100,000 (floor)
    ],
)
def test_temporary_income(revenue: int, expenses: int, expected: int) -> None:
    """一時所得 = (収入 − 支出 − ¥500k) × 1/2 (>= 0)."""
    assert temporary_income(revenue, expenses) == expected


def test_dividend_income_passthrough() -> None:
    """配当所得 (総合課税) se pasa tal cual."""
    assert dividend_income(200_000) == 200_000


def test_compute_all_incomes_sums(rules) -> None:
    """compute_all_incomes suma todos los 所得 (合計所得金額)."""
    incomes = [
        IncomeInput(kind=IncomeKind.KYUYO, revenue=4_000_000),
        IncomeInput(kind=IncomeKind.ZATSU, revenue=500_000, expenses=100_000),
    ]
    breakdown, total = compute_all_incomes(incomes, rules)
    assert len(breakdown) == 2
    assert breakdown[0].amount == 2_760_000  # 給与
    assert breakdown[1].amount == 400_000  # 雑
    assert total == 3_160_000


def test_multiple_salary_sources_use_one_deduction(rules) -> None:
    incomes = [
        IncomeInput(kind=IncomeKind.KYUYO, revenue=2_000_000, label="Empresa A"),
        IncomeInput(kind=IncomeKind.KYUYO, revenue=3_000_000, label="Empresa B"),
    ]
    breakdown, total = compute_all_incomes(incomes, rules)
    assert total == 3_560_000
    assert len(breakdown) == 1
    assert breakdown[0].amount == 3_560_000


def test_temporary_income_uses_one_annual_special_deduction(rules) -> None:
    incomes = [
        IncomeInput(kind=IncomeKind.ICHIJI, revenue=400_000),
        IncomeInput(kind=IncomeKind.ICHIJI, revenue=400_000),
    ]
    breakdown, total = compute_all_incomes(incomes, rules)
    assert total == 150_000
    assert len(breakdown) == 1
    assert breakdown[0].amount == 150_000


@pytest.mark.parametrize(
    ("ordinary", "loss", "expected"),
    [(0, 300_000, 350_000), (500_000, 300_000, 700_000),
     (100_000, 300_000, 400_000), (0, 1_500_000, 0)],
)
def test_loss_offset_precedes_halving_temporary_income(
    rules, ordinary: int, loss: int, expected: int,
) -> None:
    incomes = [
        IncomeInput(kind=IncomeKind.JIGYO, amount=-loss),
        IncomeInput(kind=IncomeKind.HAITO, amount=ordinary),
        IncomeInput(kind=IncomeKind.ICHIJI, revenue=1_500_000),
    ]
    _, total = compute_all_incomes(incomes, rules)
    assert total == expected


def test_loss_offset_jigyo_against_kyuyo(rules) -> None:
    """損益通算: la perdida del 事業 (赤字) se RESTA del 給与所得 (research 01 §2).

    給与 ¥5,000,000 -> 給与所得 ¥3,560,000 (control 給与所得控除).
    事業 perdida ¥-300,000 -> 損益通算 -> total = 3,560,000 - 300,000 = 3,260,000.
    """
    incomes = [
        IncomeInput(kind=IncomeKind.KYUYO, revenue=5_000_000),
        IncomeInput(kind=IncomeKind.JIGYO, amount=-300_000),
    ]
    breakdown, total = compute_all_incomes(incomes, rules)
    assert breakdown[0].amount == 3_560_000  # 給与所得
    assert breakdown[1].amount == -300_000  # 事業 赤字 (signo respetado)
    assert total == 3_260_000  # 損益通算 aplicado


def test_loss_offset_capped_at_zero(rules) -> None:
    """損益通算: el 合計所得金額 no baja de 0 aunque la perdida supere el resto."""
    incomes = [
        IncomeInput(kind=IncomeKind.KYUYO, revenue=2_000_000),  # 給与所得 1,320,000
        IncomeInput(kind=IncomeKind.JIGYO, amount=-5_000_000),  # perdida enorme
    ]
    _, total = compute_all_incomes(incomes, rules)
    assert total == 0


def test_real_estate_loss_offsets(rules) -> None:
    """不動産 赤字 tambien es 損益通算可能 (research 01 §2)."""
    incomes = [
        IncomeInput(kind=IncomeKind.KYUYO, revenue=5_000_000),  # 給与所得 3,560,000
        IncomeInput(kind=IncomeKind.FUDOSAN, revenue=100_000, expenses=400_000),  # -300k
    ]
    _, total = compute_all_incomes(incomes, rules)
    assert total == 3_260_000


def test_owner_scenario_loss_offset_gives_refund(rules) -> None:
    """Ejemplo sintético: 給与 5M (源泉 300k) + 事業 副業 赤字 -> 還付 (research 01 §2).

    給与 ¥5,000,000 (源泉 ¥300,000) + 事業 売上 ¥200,000 − 経費 ¥500,000 = pérdida
    ¥-300,000. Con 損益通算, la pérdida baja el 課税所得 y el 源泉 retenido del
    sueldo supera el impuesto recalculado -> final_amount NEGATIVO (還付).
    """
    inp = TaxCalculationInput(
        year=2025,
        incomes=[
            {"kind": "kyuyo", "revenue": 5_000_000},
            {"kind": "jigyo", "amount": -300_000},  # 売上 200k − 経費 500k
        ],
        deductions={"social_insurance": 700_000},
        withholding=WithholdingInput(withholding_tax=300_000),
    )
    result = calculate(inp, rules)
    assert result.total_income == 3_260_000  # 損益通算 aplicado (3.56M − 0.3M)
    assert result.final_amount < 0  # 還付
    assert result.final_amount == -214_236

    # Sin la pérdida (事業 = 0), el impuesto seria mayor: la pérdida genera 還付 extra.
    inp_no_loss = TaxCalculationInput(
        year=2025,
        incomes=[{"kind": "kyuyo", "revenue": 5_000_000}],
        deductions={"social_insurance": 700_000},
        withholding=WithholdingInput(withholding_tax=300_000),
    )
    no_loss = calculate(inp_no_loss, rules)
    assert no_loss.total_tax > result.total_tax  # la pérdida baja el impuesto
