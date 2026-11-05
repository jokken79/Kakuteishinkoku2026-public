"""Servicio de integracion entre las `Deduction` persistidas y la calculadora.

Puente entre la capa de persistencia (entidad `Deduction`, una fila por tipo de
所得控除 registrado por el usuario en el wizard) y la calculadora pura
(`DeductionInput`). Tambien estima el 節税額 (ahorro) marginal de una deduccion:
cuanto baja el 所得税 (+復興税) por cada yen deducido, segun el tramo del 速算表.

La estimacion del ahorro usa el calculo real de impuesto (no una tasa fija):
compara el impuesto con y sin la deduccion, de modo que respeta el escalonado
del 基礎控除, los pisos/topes y el redondeo del 課税所得.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from app.domain.tax.dependents import classify_dependents
from app.domain.tax.income_tax import calculate
from app.domain.tax.schemas import (
    DeductionInput,
    Dependent,
    DependentInput,
    DependentKind,
    IncomeInput,
    TaxCalculationInput,
)
from app.models.entities import Deduction
from app.models.enums import DeductionType
from app.services.tax_rules import TaxRules

logger = logging.getLogger(__name__)

# Mapa type -> campo de `DeductionInput` que recibe el monto directamente.
# 基礎控除 (kiso) se calcula solo (escalonado), no se persiste como input.
_DIRECT_FIELD: dict[DeductionType, str] = {
    DeductionType.SHAKAI_HOKEN: "social_insurance",
    DeductionType.SEIMEI_HOKEN: "life_insurance",
    DeductionType.JISHIN_HOKEN: "earthquake_insurance",
    DeductionType.IDECO: "ideco",
    DeductionType.FURUSATO: "furusato",
    DeductionType.HAIGUSHA: "spouse_deduction",
}

# Categoria de 扶養親族 por defecto cuando una fila `fuyo` no especifica `kind`.
_DEFAULT_DEPENDENT_KIND = DependentKind.GENERAL


def _dependents_from_meta(meta: dict[str, Any], year: int) -> list[Dependent]:
    """Traduce el `meta` de una fila `fuyo` a una lista de `Dependent`.

    Soporta dos formatos (en orden de prioridad):

    1. **Estructurado (research 08)**: ``meta["dependents"]`` es una lista de
       dicts con los campos de `DependentInput` (nombre, fecha de nacimiento,
       ingreso, residencia, 同居/別居, 国外居住…). Se clasifican con
       `classify_dependents` y se proyecta su categoria al calculo.
    2. **Legacy**: ``meta["kind"]`` + ``meta["count"]`` (formato previo). Se
       mantiene por compatibilidad con filas ya persistidas.

    Args:
        meta: Metadatos de la fila `fuyo`.

    Returns:
        Lista de `Dependent` (categoria ya resuelta) para la calculadora.
    """
    raw_deps = meta.get("dependents")
    if isinstance(raw_deps, list):
        inputs: list[DependentInput] = []
        for raw in raw_deps:
            if not isinstance(raw, dict):
                continue
            try:
                inputs.append(DependentInput(**raw))
            except (TypeError, ValueError) as exc:
                logger.warning("Dependiente 扶養 inválido en meta, se omite: %s", exc)
        results = classify_dependents(inputs, year)
        # Solo los que aportan 控除 (qualifies) suman; 年少/対象外 se registran pero
        # no entran a la calculadora (su monto es 0 de todos modos).
        return [r.to_dependent() for r in results if r.qualifies]

    # Legacy: meta.kind + meta.count.
    count = int(meta.get("count", 1))
    kind_raw = meta.get("kind", _DEFAULT_DEPENDENT_KIND.value)
    try:
        kind = DependentKind(kind_raw)
    except ValueError:
        kind = _DEFAULT_DEPENDENT_KIND
    return [Dependent(kind=kind) for _ in range(max(count, 0))]


def deductions_to_input(deductions: list[Deduction], *, year: int) -> DeductionInput:
    """Agrega una lista de `Deduction` persistidas en un `DeductionInput`.

    Cada fila aporta su `amount` al campo correspondiente de la calculadora.
    El 医療費控除 (iryohi) se modela con `medical_expenses`/`medical_reimbursement`
    (la fila guarda el gasto neto en `amount` y el reembolso opcional en `meta`).
    Las filas `fuyo` se traducen a `Dependent` segun `meta.kind` (default 一般).

    Args:
        deductions: Filas de deduccion del 年度 (una por tipo registrado).

    Returns:
        `DeductionInput` listo para `calculate()`.
    """
    fields: dict[str, int] = {}
    dependents: list[Dependent] = []
    medical_expenses = 0
    medical_reimbursement = 0
    ordinary_disability_self = False

    for ded in deductions:
        meta = ded.meta or {}
        if ded.type in _DIRECT_FIELD:
            fields[_DIRECT_FIELD[ded.type]] = (
                fields.get(_DIRECT_FIELD[ded.type], 0) + ded.amount
            )
        elif ded.type == DeductionType.IRYOHI:
            medical_expenses += ded.amount
            medical_reimbursement += int(cast(int, meta.get("reimbursement", 0)))
        elif ded.type == DeductionType.FUYO:
            dependents.extend(_dependents_from_meta(meta, year))
        elif ded.type == DeductionType.DISABILITY_SELF:
            ordinary_disability_self = True
        elif ded.type == DeductionType.OTHER:
            # 'other' suma directo al bucket de 障害者/寡婦/勤労学生 via campo libre.
            fields["disability_deduction"] = (
                fields.get("disability_deduction", 0) + ded.amount
            )
        # kiso se ignora: lo calcula la calculadora (escalonado, no es input).
        # housing_loan se ignora aqui: es 税額控除 (se resta del impuesto, no de la
        # base imponible). Se proyecta como `tax_credit` via `total_tax_credits`.

    return DeductionInput(
        medical_expenses=medical_expenses,
        medical_reimbursement=medical_reimbursement,
        dependents=dependents,
        ordinary_disability_self=ordinary_disability_self,
        **fields,
    )


def total_tax_credits(deductions: list[Deduction]) -> int:
    """Suma los 税額控除 persistidos como `Deduction` (住宅ローン控除, etc.).

    A diferencia de las 所得控除 (que bajan la base imponible), los 税額控除 se
    restan directamente del 所得税 calculado. Se almacenan como `Deduction` por
    homogeneidad, pero el calculo los consume via `TaxCalculationInput.tax_credits`,
    no via `DeductionInput`.

    Args:
        deductions: Filas de deduccion del 年度.

    Returns:
        Σ de los 税額控除 (>= 0). Hoy solo 住宅ローン控除 (HOUSING_LOAN).
    """
    def is_applied(deduction: Deduction) -> bool:
        meta = deduction.meta if isinstance(deduction.meta, dict) else {}
        claim_status = meta.get("claim_status", "applied")
        return claim_status in {"applied", "approved"}

    return sum(
        d.amount
        for d in deductions
        if d.type == DeductionType.HOUSING_LOAN and d.amount > 0 and is_applied(d)
    )


def estimate_tax_saving(
    deduction: Deduction,
    other_deductions: list[Deduction],
    incomes: list[dict[str, Any]],
    rules: TaxRules,
    *,
    year: int,
    filing_type: str = "aoiro_65",
) -> int:
    """Estima el 節税額 (ahorro) marginal de UNA deduccion.

    Calcula el impuesto total (所得税 + 復興税) con y sin la deduccion dada
    (manteniendo el resto fijo) y devuelve la diferencia. Refleja el tramo
    marginal real del contribuyente.

    Args:
        deduction: La deduccion cuyo ahorro se estima.
        other_deductions: Las demas deducciones registradas (contexto fijo).
        incomes: Fuentes de ingreso (dicts `IncomeInput`-compatibles).
        rules: Parametros fiscales del anio.
        year: Anio fiscal.
        filing_type: Modalidad de declaracion.

    Returns:
        Ahorro estimado en yenes (>= 0). 0 si la deduccion no mueve el impuesto
        (ej. el contribuyente ya no paga impuesto).
    """
    with_input = deductions_to_input([*other_deductions, deduction], year=year)
    without_input = deductions_to_input(other_deductions, year=year)

    tax_with = calculate(
        TaxCalculationInput(
            year=year,
            filing_type=filing_type,
            incomes=cast(list[IncomeInput], incomes),
            deductions=with_input,
        ),
        rules,
    ).total_tax
    tax_without = calculate(
        TaxCalculationInput(
            year=year,
            filing_type=filing_type,
            incomes=cast(list[IncomeInput], incomes),
            deductions=without_input,
        ),
        rules,
    ).total_tax
    return max(tax_without - tax_with, 0)
