"""Cálculo puro para repartir importes mixtos sin modificar comprobantes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.entities import Transaction


@dataclass(frozen=True)
class MixedLine:
    """Importe bruto de una línea del comprobante; tasa ``None`` si es desconocida."""

    gross: int
    tax_rate: int | None = None


@dataclass(frozen=True)
class AllocatedLine:
    original: MixedLine
    business: int
    personal: int


@dataclass(frozen=True)
class MixedAllocation:
    original_total: int
    business_total: int
    personal_total: int
    numerator: int
    denominator: int
    lines: tuple[AllocatedLine, ...]


def allocate_mixed_expense(
    original_total: int,
    lines: list[MixedLine],
    numerator: int,
    denominator: int,
) -> MixedAllocation:
    """Reparte un importe con razón exacta y restos mayores por línea.

    Es una estimación mecánica: el usuario debe verificar que cada concepto y
    el criterio de reparto sean fiscalmente aplicables. No calcula el impuesto
    de consumo ni modifica datos. Trunca el total de negocio al yen y reparte
    los yenes residuales de forma determinista entre las líneas.
    """
    if (
        isinstance(original_total, bool)
        or not isinstance(original_total, int)
        or original_total < 0
    ):
        raise ValueError("El total debe ser un número entero de yenes no negativo.")
    if (
        isinstance(numerator, bool)
        or isinstance(denominator, bool)
        or not isinstance(numerator, int)
        or not isinstance(denominator, int)
        or denominator <= 0
        or numerator < 0
        or numerator > denominator
    ):
        raise ValueError("La proporción debe estar entre cero y uno.")
    if not lines:
        raise ValueError("Se requiere al menos una línea de gasto.")
    for line in lines:
        if isinstance(line.gross, bool) or not isinstance(line.gross, int) or line.gross < 0:
            raise ValueError("Cada línea debe tener un importe entero no negativo.")
    if sum(line.gross for line in lines) != original_total:
        raise ValueError("Las líneas deben sumar exactamente el total original.")

    business_total = original_total * numerator // denominator
    allocated = [line.gross * numerator // denominator for line in lines]
    residual = business_total - sum(allocated)
    order = sorted(
        range(len(lines)),
        key=lambda index: (-(lines[index].gross * numerator % denominator), index),
    )
    for index in order[:residual]:
        allocated[index] += 1
    split_lines = tuple(
        AllocatedLine(original=line, business=part, personal=line.gross - part)
        for line, part in zip(lines, allocated, strict=True)
    )
    return MixedAllocation(
        original_total=original_total,
        business_total=business_total,
        personal_total=original_total - business_total,
        numerator=numerator,
        denominator=denominator,
        lines=split_lines,
    )


def transaction_allocation(tx: Transaction) -> MixedAllocation | None:
    """Calcula el reparto guardado; rechaza datos modificados o inconsistentes."""
    meta = tx.business_allocation
    if meta is None:
        return None
    if meta.get("original_total") != tx.total_amount:
        raise ValueError("El importe original cambió después del reparto.")
    numerator = meta.get("numerator")
    denominator = meta.get("denominator")
    if type(numerator) is not int or type(denominator) is not int:
        raise ValueError("La proporción guardada no es válida.")
    source_lines = tx.tax_lines or []
    lines: list[MixedLine] = []
    for item in source_lines:
        base, tax, rate = item.get("base"), item.get("tax"), item.get("rate")
        if type(base) is not int or type(tax) is not int:
            raise ValueError("El desglose fiscal del comprobante está incompleto.")
        if rate is not None and type(rate) is not int:
            raise ValueError("La tasa de la línea no es válida.")
        lines.append(MixedLine(gross=base + tax, tax_rate=rate))
    if not lines:
        lines = [MixedLine(gross=tx.total_amount)]
    return allocate_mixed_expense(tx.total_amount, lines, numerator, denominator)
