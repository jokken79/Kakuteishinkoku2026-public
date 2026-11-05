"""Pipeline de calculo del 所得税 — 7 pasos (plan 03 §3).

    1. Clasificar/calcular cada 所得 -> 合計所得金額.
    2. (Separacion 総合/分離: en este MVP solo 総合課税.)
    3. Sumar 所得控除 (基礎 escalonado + 社会保険 + 医療費 + ...).
    4. 課税所得 = 合計所得 − Σ控除 ; aplicar 速算表 -> 基準所得税額.
    5. Restar 税額控除.
    6. + 復興特別所得税 (基準額 × 2.1%).
    7. − 源泉徴収 − 予定納税 -> 納付額 (>0) / 還付金 (<0).
"""

import logging

from app.domain.tax.deductions import compute_deductions
from app.domain.tax.income import compute_all_incomes
from app.domain.tax.schemas import (
    TaxCalculationInput,
    TaxCalculationResult,
)
from app.services.tax_rules import TaxRules, load_tax_rules

logger = logging.getLogger(__name__)

# El 課税所得金額 se redondea a la baja al millar (¥1,000) antes del 速算表
# (国税庁: 課税される所得金額は千円未満切り捨て).
TAXABLE_INCOME_ROUNDING = 1_000


def _round_down_taxable_income(amount: int) -> int:
    """Redondea el 課税所得 a la baja al millar (千円未満切り捨て).

    Args:
        amount: 課税所得 sin redondear (puede ser negativo).

    Returns:
        課税所得金額 redondeado a la baja a ¥1,000 (>= 0).
    """
    if amount <= 0:
        return 0
    return (amount // TAXABLE_INCOME_ROUNDING) * TAXABLE_INCOME_ROUNDING


def apply_tax_table(taxable_income: int, rules: TaxRules) -> int:
    """Aplica el 速算表: 所得税額 = 課税所得 × 税率 − 控除額.

    Args:
        taxable_income: 課税所得金額 (ya redondeado a la baja).
        rules: Parametros fiscales (`income_tax_brackets`).

    Returns:
        所得税額 base (>= 0).
    """
    if taxable_income <= 0:
        return 0
    bracket = rules.bracket_for(taxable_income)
    tax = int(taxable_income * bracket.rate) - bracket.deduction
    return max(tax, 0)


def reconstruction_tax(income_tax_after_credits: int, rules: TaxRules) -> int:
    """Calcula el 復興特別所得税 = 基準所得税額 × 2.1% (truncado).

    Args:
        income_tax_after_credits: 基準所得税額 (tras 税額控除).
        rules: Parametros fiscales (`reconstruction_tax_rate`).

    Returns:
        復興特別所得税 (entero, truncado).
    """
    return int(income_tax_after_credits * rules.reconstruction_tax_rate)


def calculate(
    input_data: TaxCalculationInput, rules: TaxRules | None = None
) -> TaxCalculationResult:
    """Ejecuta el pipeline completo de 7 pasos.

    Args:
        input_data: Entrada completa del calculo.
        rules: Parametros fiscales del anio. Si es `None`, se cargan segun
            `input_data.year`.

    Returns:
        `TaxCalculationResult` con el desglose completo. `final_amount` negativo
        indica 還付金 (devolucion).
    """
    if rules is None:
        rules = load_tax_rules(input_data.year)

    # Paso 1: 所得 de cada fuente + 合計所得金額.
    income_breakdown, total_income = compute_all_incomes(input_data.incomes, rules)

    # Paso 3: 所得控除 (depende del 合計所得 para 基礎控除 escalonado y pisos/topes).
    deduction_breakdown, total_deductions = compute_deductions(
        input_data.deductions, total_income, rules
    )

    # Paso 4: 課税所得 = 合計所得 − Σ控除, redondeado a la baja al millar.
    raw_taxable = total_income - total_deductions
    taxable_income = _round_down_taxable_income(raw_taxable)
    income_tax_base = apply_tax_table(taxable_income, rules)

    # Paso 5: restar 税額控除 (no baja de 0).
    tax_credits = min(input_data.tax_credits, income_tax_base)
    income_tax_after_credits = income_tax_base - tax_credits

    # Paso 6: + 復興特別所得税.
    recon_tax = reconstruction_tax(income_tax_after_credits, rules)
    total_tax = income_tax_after_credits + recon_tax

    # Paso 7: − 源泉徴収 − 予定納税 -> 納付額 / 還付金.
    withholding_total = (
        input_data.withholding.withholding_tax + input_data.withholding.estimated_prepayment
    )
    declared_tax = total_tax - input_data.withholding.withholding_tax
    if declared_tax > 0:
        declared_tax = declared_tax // 100 * 100
    final_amount = declared_tax - input_data.withholding.estimated_prepayment
    if final_amount > 0:
        final_amount = final_amount // 100 * 100

    return TaxCalculationResult(
        year=input_data.year,
        income_breakdown=income_breakdown,
        total_income=total_income,
        deduction_breakdown=deduction_breakdown,
        total_income_deductions=total_deductions,
        taxable_income=taxable_income,
        income_tax_base=income_tax_base,
        tax_credits=tax_credits,
        income_tax_after_credits=income_tax_after_credits,
        reconstruction_tax=recon_tax,
        total_tax=total_tax,
        withholding_total=withholding_total,
        withholding_tax=input_data.withholding.withholding_tax,
        estimated_prepayment=input_data.withholding.estimated_prepayment,
        final_amount=final_amount,
    )
