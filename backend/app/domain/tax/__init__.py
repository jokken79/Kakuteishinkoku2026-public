"""Calculadora fiscal del 所得税 (logica pura, montos enteros JPY).

Submodulos:
    schemas: modelos Pydantic de entrada/salida.
    income: calculo de cada uno de los 10 所得.
    deductions: calculo de las 所得控除 (incl. 基礎控除 escalonado).
    income_tax: pipeline de 7 pasos -> 納付額 / 還付金.
"""

from app.domain.tax.income_tax import calculate
from app.domain.tax.schemas import (
    DeductionInput,
    IncomeInput,
    TaxCalculationInput,
    TaxCalculationResult,
    WithholdingInput,
)

__all__ = [
    "DeductionInput",
    "IncomeInput",
    "TaxCalculationInput",
    "TaxCalculationResult",
    "WithholdingInput",
    "calculate",
]
