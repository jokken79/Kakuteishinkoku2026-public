"""Cálculos monetarios de documentos comerciales japoneses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.models.enums import SalesPriceMode, SalesTaxCategory, TaxRoundingMode


@dataclass(frozen=True)
class CalculatedLine:
    """Línea normalizada a yenes enteros."""

    amount: int
    tax_category: SalesTaxCategory


@dataclass(frozen=True)
class DocumentTotals:
    """Totales persistibles del documento."""

    subtotal: int
    tax_8: int
    tax_10: int
    total: int


def line_amount(quantity: Decimal, unit_price: int, discount_amount: int = 0) -> int:
    """Calcula el importe de línea, redondeado a un yen.

    El descuento se aplica después de multiplicar cantidad por precio. Una línea
    nunca puede producir un importe negativo.
    """
    if quantity <= 0:
        raise ValueError("数量は0より大きい値を入力してください。")
    if unit_price < 0 or discount_amount < 0:
        raise ValueError("単価と値引きは0以上で入力してください。")
    gross = (quantity * Decimal(unit_price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    amount = int(gross) - discount_amount
    if amount < 0:
        raise ValueError("値引き額が明細金額を超えています。")
    return amount


def _round_tax(value: Decimal, mode: TaxRoundingMode) -> int:
    rounding = {
        TaxRoundingMode.FLOOR: ROUND_FLOOR,
        TaxRoundingMode.ROUND: ROUND_HALF_UP,
        TaxRoundingMode.CEIL: ROUND_CEILING,
    }[mode]
    return int(value.quantize(Decimal("1"), rounding=rounding))


def calculate_totals(
    lines: list[CalculatedLine],
    *,
    rounding_mode: TaxRoundingMode,
    price_mode: SalesPriceMode,
) -> DocumentTotals:
    """Calcula impuesto una vez por tasa, como exige el invoice japonés."""
    group_8 = sum(line.amount for line in lines if line.tax_category == SalesTaxCategory.REDUCED_8)
    group_10 = sum(
        line.amount for line in lines if line.tax_category == SalesTaxCategory.STANDARD_10
    )
    untaxed = sum(
        line.amount
        for line in lines
        if line.tax_category in {SalesTaxCategory.EXEMPT, SalesTaxCategory.OUT_OF_SCOPE}
    )

    if price_mode == SalesPriceMode.INCLUSIVE:
        tax_8 = _round_tax(Decimal(group_8) * Decimal(8) / Decimal(108), rounding_mode)
        tax_10 = _round_tax(Decimal(group_10) * Decimal(10) / Decimal(110), rounding_mode)
        subtotal = group_8 + group_10 + untaxed - tax_8 - tax_10
        total = group_8 + group_10 + untaxed
    else:
        tax_8 = _round_tax(Decimal(group_8) * Decimal("0.08"), rounding_mode)
        tax_10 = _round_tax(Decimal(group_10) * Decimal("0.10"), rounding_mode)
        subtotal = group_8 + group_10 + untaxed
        total = subtotal + tax_8 + tax_10

    return DocumentTotals(subtotal=subtotal, tax_8=tax_8, tax_10=tax_10, total=total)
