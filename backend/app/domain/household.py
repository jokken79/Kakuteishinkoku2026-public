"""家計簿 — lógica de negocio del libro de gastos personales (NO fiscal).

Módulo 100% aditivo e independiente de la calculadora fiscal. Provee:

- Filtrado de `HouseholdExpense` por mes/año (sobre el campo `date`).
- Agregación del total por 費目 (categoría) de un mes (`summary`).

Los gastos del 家計簿 NUNCA entran al 仕訳 ni al cálculo del 所得税/住民税/消費税.
"""

from __future__ import annotations

import calendar
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import HouseholdExpense
from app.models.enums import HouseholdCategory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CategoryTotal:
    """Total de un 費目 dentro de un mes.

    Args:
        category: Categoría 家計簿.
        total: Suma de los montos (yenes) de esa categoría en el mes.
        count: Cantidad de gastos de esa categoría en el mes.
    """

    category: HouseholdCategory
    total: int
    count: int


@dataclass(frozen=True)
class MonthlySummary:
    """Resumen mensual del 家計簿.

    Args:
        year: Año gregoriano del resumen.
        month: Mes (1-12) del resumen.
        total: Total general del mes (yenes).
        by_category: Desglose por 費目 (solo categorías con gastos).
    """

    year: int
    month: int
    total: int
    by_category: list[CategoryTotal]


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    """Devuelve el primer y último día del mes (inclusive).

    Args:
        year: Año gregoriano.
        month: Mes (1-12).

    Returns:
        Tupla ``(primer_día, último_día)`` del mes.
    """
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def list_expenses(
    session: Session, *, year: int, month: int
) -> list[HouseholdExpense]:
    """Lista los gastos personales de un mes, ordenados por fecha descendente.

    Args:
        session: Sesión de SQLAlchemy.
        year: Año gregoriano.
        month: Mes (1-12).

    Returns:
        Lista de `HouseholdExpense` del mes (más recientes primero).
    """
    start, end = _month_bounds(year, month)
    stmt = (
        select(HouseholdExpense)
        .where(HouseholdExpense.date >= start)
        .where(HouseholdExpense.date <= end)
        .order_by(HouseholdExpense.date.desc(), HouseholdExpense.created_at.desc())
    )
    return list(session.scalars(stmt).all())


def summarize_month(
    session: Session, *, year: int, month: int
) -> MonthlySummary:
    """Calcula el total del mes y el desglose por 費目.

    Args:
        session: Sesión de SQLAlchemy.
        year: Año gregoriano.
        month: Mes (1-12).

    Returns:
        `MonthlySummary` con el total general y el total por categoría
        (solo las categorías con al menos un gasto en el mes).
    """
    expenses = list_expenses(session, year=year, month=month)

    totals: dict[HouseholdCategory, int] = defaultdict(int)
    counts: dict[HouseholdCategory, int] = defaultdict(int)
    for expense in expenses:
        totals[expense.category] += expense.amount
        counts[expense.category] += 1

    by_category = [
        CategoryTotal(category=cat, total=totals[cat], count=counts[cat])
        # Orden estable: por monto descendente, luego por nombre de la categoría.
        # `str(c)` porque el valor leído de la BD puede venir como str plano
        # (StrEnum almacenado en una columna String): str(StrEnum) == su value.
        for cat in sorted(totals, key=lambda c: (-totals[c], str(c)))
    ]
    grand_total = sum(totals.values())

    return MonthlySummary(
        year=year,
        month=month,
        total=grand_total,
        by_category=by_category,
    )
