"""Golden tests de cálculo para 売上書類."""

from decimal import Decimal

import pytest

from app.models.enums import SalesPriceMode, SalesTaxCategory, TaxRoundingMode
from app.services.sales_documents.calculations import (
    CalculatedLine,
    calculate_totals,
    line_amount,
)


def test_line_amount_rounds_quantity_to_one_yen() -> None:
    assert line_amount(Decimal("1.25"), 1_001, 1) == 1_250


def test_exclusive_prices_calculate_once_per_rate() -> None:
    totals = calculate_totals(
        [
            CalculatedLine(10_000, SalesTaxCategory.STANDARD_10),
            CalculatedLine(1_000, SalesTaxCategory.REDUCED_8),
            CalculatedLine(500, SalesTaxCategory.EXEMPT),
        ],
        rounding_mode=TaxRoundingMode.FLOOR,
        price_mode=SalesPriceMode.EXCLUSIVE,
    )
    assert totals.subtotal == 11_500
    assert totals.tax_10 == 1_000
    assert totals.tax_8 == 80
    assert totals.total == 12_580


def test_inclusive_prices_extract_tax_without_changing_total() -> None:
    totals = calculate_totals(
        [
            CalculatedLine(11_000, SalesTaxCategory.STANDARD_10),
            CalculatedLine(1_080, SalesTaxCategory.REDUCED_8),
        ],
        rounding_mode=TaxRoundingMode.FLOOR,
        price_mode=SalesPriceMode.INCLUSIVE,
    )
    assert totals.subtotal == 11_000
    assert totals.tax_10 == 1_000
    assert totals.tax_8 == 80
    assert totals.total == 12_080


def test_discount_cannot_exceed_line_amount() -> None:
    with pytest.raises(ValueError, match="値引き額"):
        line_amount(Decimal("1"), 1_000, 1_001)
