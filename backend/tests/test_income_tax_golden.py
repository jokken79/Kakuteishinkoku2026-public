"""Golden tests del pipeline de 所得税 (`app.domain.tax.income_tax`).

Cada test documenta el calculo manual paso a paso segun las formulas oficiales
del 国税庁 (令和7年分), para trazabilidad y validacion posterior contra el
確定申告書等作成コーナー del NTA.
"""

import pytest

from app.domain.tax.income_tax import (
    apply_tax_table,
    calculate,
    reconstruction_tax,
)
from app.domain.tax.schemas import (
    DeductionInput,
    IncomeInput,
    IncomeKind,
    TaxCalculationInput,
    WithholdingInput,
)
from app.services.tax_rules import load_tax_rules


@pytest.fixture
def rules():
    """Parametros fiscales 2025 (令和7)."""
    return load_tax_rules(2025)


def test_golden_kojin_jigyo_menzei(rules) -> None:
    """個人事業主 免税, 事業所得 ¥5,000,000 (青色65万 ya aplicado).

    Calculo manual paso a paso:
      1. 事業所得 = ¥5,000,000 (input ya neto del 青色特別控除).
         合計所得金額 = ¥5,000,000.
      3. 所得控除:
         - 基礎控除: 合計所得 ¥5,000,000 cae en tramo ¥4,890,000-¥6,550,000
           -> ¥630,000 (令和7 temporal).
         - 社会保険料控除 = ¥600,000.
         Σ控除 = 630,000 + 600,000 = ¥1,230,000.
      4. 課税所得 = 5,000,000 − 1,230,000 = ¥3,770,000 (ya multiplo de 1,000).
         速算表 (tramo <= ¥6,949,000): 20%, 控除額 ¥427,500.
         所得税基準額 = 3,770,000 × 0.20 − 427,500 = 754,000 − 427,500 = ¥326,500.
      5. 税額控除 = 0 -> ¥326,500.
      6. 復興特別所得税 = int(326,500 × 0.021) = int(6,856.5) = ¥6,856.
         年税額 = 326,500 + 6,856 = ¥333,356.
      7. 源泉徴収 + 予定納税 = 0. 納付額 = ¥333,300 (100円未満切捨て).
    """
    payload = TaxCalculationInput(
        year=2025,
        filing_type="aoiro_65",
        incomes=[IncomeInput(kind=IncomeKind.JIGYO, amount=5_000_000, label="事業")],
        deductions=DeductionInput(social_insurance=600_000),
    )
    result = calculate(payload, rules)

    assert result.total_income == 5_000_000
    assert result.deduction_breakdown.kiso == 630_000
    assert result.total_income_deductions == 1_230_000
    assert result.taxable_income == 3_770_000
    assert result.income_tax_base == 326_500
    assert result.income_tax_after_credits == 326_500
    assert result.reconstruction_tax == 6_856
    assert result.total_tax == 333_356
    assert result.final_amount == 333_300  # 納付額


def test_golden_kyuyo_plus_zatsu(rules) -> None:
    """給与所得 + 副業 雑所得.

    Calculo manual paso a paso:
      1. 給与収入 ¥4,000,000: tramo ¥3.6M-¥6.6M -> 控除 = 4,000,000×0.2 + 440,000
         = 800,000 + 440,000 = ¥1,240,000. 給与所得 = 4,000,000 − 1,240,000
         = ¥2,760,000.
         雑所得 = 収入 ¥500,000 − 経費 ¥100,000 = ¥400,000.
         合計所得金額 = 2,760,000 + 400,000 = ¥3,160,000.
      3. 所得控除:
         - 基礎控除: ¥3,160,000 en tramo ¥1,320,000-¥3,360,000 -> ¥880,000 (temporal).
         - 社会保険料控除 = ¥500,000.
         Σ控除 = 880,000 + 500,000 = ¥1,380,000.
      4. 課税所得 = 3,160,000 − 1,380,000 = ¥1,780,000.
         速算表 (tramo <= ¥1,949,000): 5%, 控除額 ¥0.
         所得税基準額 = 1,780,000 × 0.05 = ¥89,000.
      6. 復興特別所得税 = int(89,000 × 0.021) = int(1,869) = ¥1,869.
         年税額 = 89,000 + 1,869 = ¥90,869.
      7. sin retenciones -> 納付額 = ¥90,869.
    """
    payload = TaxCalculationInput(
        year=2025,
        incomes=[
            IncomeInput(kind=IncomeKind.KYUYO, revenue=4_000_000, label="本業"),
            IncomeInput(kind=IncomeKind.ZATSU, revenue=500_000, expenses=100_000, label="副業"),
        ],
        deductions=DeductionInput(social_insurance=500_000),
    )
    result = calculate(payload, rules)

    assert result.income_breakdown[0].amount == 2_760_000
    assert result.income_breakdown[1].amount == 400_000
    assert result.total_income == 3_160_000
    assert result.deduction_breakdown.kiso == 880_000
    assert result.total_income_deductions == 1_380_000
    assert result.taxable_income == 1_780_000
    assert result.income_tax_base == 89_000
    assert result.reconstruction_tax == 1_869
    assert result.total_tax == 90_869
    assert result.final_amount == 90_800


def test_prepayment_is_subtracted_after_declared_tax_is_rounded(rules) -> None:
    result = calculate(TaxCalculationInput(
        year=2025,
        incomes=[IncomeInput(kind=IncomeKind.JIGYO, amount=5_000_000)],
        deductions=DeductionInput(social_insurance=600_000),
        withholding=WithholdingInput(withholding_tax=100_000, estimated_prepayment=240_000),
    ), rules)
    assert result.total_tax == 333_356
    assert result.withholding_tax == 100_000
    assert result.estimated_prepayment == 240_000
    assert result.final_amount == -6_700


def test_golden_kanpu_refund(rules) -> None:
    """還付金 por 源泉徴収 alto (caso del 給与+雑 con retencion ¥200,000).

    Mismos ingresos/deducciones que el caso anterior:
      年税額 = ¥90,869.
      源泉徴収税額 = ¥200,000, 予定納税 = ¥0.
      納付額 = 90,869 − 200,000 = −¥109,131 -> 還付金 ¥109,131.
    """
    payload = TaxCalculationInput(
        year=2025,
        incomes=[
            IncomeInput(kind=IncomeKind.KYUYO, revenue=4_000_000),
            IncomeInput(kind=IncomeKind.ZATSU, revenue=500_000, expenses=100_000),
        ],
        deductions=DeductionInput(social_insurance=500_000),
        withholding=WithholdingInput(withholding_tax=200_000),
    )
    result = calculate(payload, rules)

    assert result.total_tax == 90_869
    assert result.withholding_total == 200_000
    assert result.final_amount == -109_131  # negativo = 還付金


def test_golden_kiso_kojo_levels(rules) -> None:
    """El 基礎控除 escalonado cambia el resultado segun el 合計所得 (令和7).

    Verifica que el mismo "tipo" de contribuyente con distinto 事業所得 recibe
    distinto 基礎控除 segun la tabla 令和7:
      ¥1,000,000 -> ¥950,000
      ¥3,000,000 -> ¥880,000 (tramo 1.32M-3.36M)
      ¥4,000,000 -> ¥680,000 (tramo 3.36M-4.89M)
      ¥5,000,000 -> ¥630,000 (tramo 4.89M-6.55M)
      ¥10,000,000 -> ¥580,000 (tramo 6.55M-23.5M)
    """
    expected = {
        1_000_000: 950_000,
        3_000_000: 880_000,
        4_000_000: 680_000,
        5_000_000: 630_000,
        10_000_000: 580_000,
    }
    for income, kiso in expected.items():
        payload = TaxCalculationInput(
            year=2025,
            incomes=[IncomeInput(kind=IncomeKind.JIGYO, amount=income)],
            deductions=DeductionInput(),
        )
        result = calculate(payload, rules)
        assert result.deduction_breakdown.kiso == kiso, f"income={income}"


@pytest.mark.parametrize(
    ("taxable_income", "expected_tax"),
    [
        # 速算表 令和7: cada tramo (税率, 控除額).
        (1_000_000, 50_000),  # 5%, 0 -> 50,000
        (3_000_000, 202_500),  # 10% - 97,500 -> 300,000-97,500
        (5_000_000, 572_500),  # 20% - 427,500 -> 1,000,000-427,500
        (8_000_000, 1_204_000),  # 23% - 636,000 -> 1,840,000-636,000
        (15_000_000, 3_414_000),  # 33% - 1,536,000 -> 4,950,000-1,536,000
        (30_000_000, 9_204_000),  # 40% - 2,796,000 -> 12,000,000-2,796,000
        (50_000_000, 17_704_000),  # 45% - 4,796,000 -> 22,500,000-4,796,000
    ],
)
def test_golden_sokusanhyo_each_bracket(
    taxable_income: int, expected_tax: int, rules
) -> None:
    """速算表 令和7: 所得税額 = 課税所得 × 税率 − 控除額 en cada tramo."""
    assert apply_tax_table(taxable_income, rules) == expected_tax


def test_golden_reconstruction_tax_2_1pct(rules) -> None:
    """復興特別所得税 = 基準所得税額 × 2.1% (truncado).

    Ejemplos:
      base ¥326,500 -> int(326,500 × 0.021) = int(6,856.5) = ¥6,856.
      base ¥1,000,000 -> int(21,000) = ¥21,000.
    """
    assert reconstruction_tax(326_500, rules) == 6_856
    assert reconstruction_tax(1_000_000, rules) == 21_000


def test_zero_taxable_income_no_tax(rules) -> None:
    """課税所得 0 (deducciones >= ingresos) -> 0 impuesto, sin negativos."""
    payload = TaxCalculationInput(
        year=2025,
        incomes=[IncomeInput(kind=IncomeKind.JIGYO, amount=400_000)],
        deductions=DeductionInput(social_insurance=200_000),
    )
    result = calculate(payload, rules)
    assert result.taxable_income == 0
    assert result.income_tax_base == 0
    assert result.total_tax == 0
    assert result.final_amount == 0
