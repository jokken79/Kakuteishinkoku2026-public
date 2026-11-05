"""Calculo de las 所得控除 (research 01 §3).

Cada funcion calcula una deduccion concreta; `compute_deductions` agrega el
total y un desglose. El 基礎控除 escalonado (reforma 令和7) es la pieza critica:
depende del 合計所得金額 ya calculado.
"""

import logging

from app.domain.tax.dependents import DEPENDENT_AMOUNTS as _DEPENDENT_AMOUNTS_PAIRS
from app.domain.tax.schemas import (
    DeductionBreakdown,
    DeductionInput,
    Dependent,
    DependentKind,
)
from app.services.tax_rules import TaxRules

logger = logging.getLogger(__name__)

# Montos del 扶養控除 (所得税) por categoria — research 08, 令和7. Se derivan del
# modulo `dependents` (unica fuente: alli viven tambien los montos del 住民税).
# 年少 (<16) y 対象外 NO aportan 控除 al 所得税.
DEPENDENT_AMOUNTS: dict[DependentKind, int] = {
    kind: pair[0] for kind, pair in _DEPENDENT_AMOUNTS_PAIRS.items()
}

# Tope del 医療費控除 (research 01 §3).
MEDICAL_DEDUCTION_CAP = 2_000_000
# Porcentaje del 総所得 que define el piso del 医療費控除 (5%).
MEDICAL_FLOOR_RATE = 0.05
# Tope del 寄附金控除 (ふるさと納税): 40% del 総所得.
FURUSATO_CAP_RATE = 0.40


def kiso_deduction(total_income: int, rules: TaxRules) -> int:
    """Calcula el 基礎控除 escalonado segun el 合計所得金額 (reforma 令和7).

    Args:
        total_income: 合計所得金額.
        rules: Parametros fiscales del anio (tabla `kiso_kojo`).

    Returns:
        Monto del 基礎控除.
    """
    return rules.kiso_kojo_for(total_income)


def medical_deduction(expenses: int, reimbursement: int, total_income: int, rules: TaxRules) -> int:
    """Calcula el 医療費控除 (research 01 §3).

    Formula: (gasto − reembolso) − min(¥100,000, 総所得 × 5%); tope ¥2,000,000.

    Args:
        expenses: 医療費 pagados en el anio.
        reimbursement: Reembolsos recibidos (seguros, mutual, etc.).
        total_income: 総所得金額 (base para el piso del 5%).
        rules: Parametros fiscales (`deductions.iryohi_floor`).

    Returns:
        Monto deducible del 医療費控除 (>= 0).
    """
    net_expenses = expenses - reimbursement
    if net_expenses <= 0:
        return 0
    floor = min(rules.deductions.iryohi_floor, int(total_income * MEDICAL_FLOOR_RATE))
    deductible = net_expenses - floor
    if deductible <= 0:
        return 0
    return min(deductible, MEDICAL_DEDUCTION_CAP)


def life_insurance_deduction(paid_or_computed: int, rules: TaxRules) -> int:
    """Aplica el tope global del 生命保険料控除.

    El input ya viene calculado por categorias (一般/介護医療/個人年金); aca solo
    se aplica el tope global del anio (¥120,000 en 令和7).

    Args:
        paid_or_computed: Monto de 生命保険料控除 calculado por categorias.
        rules: Parametros fiscales (`deductions.seimei_hoken_max`).

    Returns:
        Monto deducible (acotado al tope).
    """
    return min(max(paid_or_computed, 0), rules.deductions.seimei_hoken_max)


def earthquake_insurance_deduction(paid: int, rules: TaxRules) -> int:
    """Calcula el 地震保険料控除 (tope ¥50,000 en 令和7).

    Args:
        paid: 地震保険料 pagado.
        rules: Parametros fiscales (`deductions.jishin_hoken_max`).

    Returns:
        Monto deducible (acotado al tope).
    """
    return min(max(paid, 0), rules.deductions.jishin_hoken_max)


def dependent_deduction(dependents: list[Dependent]) -> int:
    """Calcula el 扶養控除 total sumando el monto por categoria.

    Args:
        dependents: Lista de familiares a cargo.

    Returns:
        扶養控除 total.
    """
    # `.get(..., 0)` en vez de indexación directa: si `DependentKind` se extiende
    # (ej. agregar 年少扶養 sin monto) un valor no mapeado NO debe reventar todo el
    # cálculo del 確定申告 con un KeyError — simplemente no aporta 控除.
    return sum(DEPENDENT_AMOUNTS.get(d.kind, 0) for d in dependents)


def furusato_deduction(donated: int, total_income: int, rules: TaxRules) -> int:
    """Calcula el 寄附金控除 (ふるさと納税): (donaciones − ¥2,000); tope 40% 総所得.

    Args:
        donated: Total donado en el anio.
        total_income: 総所得金額 (base del tope del 40%).
        rules: Parametros fiscales (`deductions.furusato_floor`).

    Returns:
        Monto deducible del 寄附金控除 (>= 0).
    """
    if donated <= rules.deductions.furusato_floor:
        return 0
    cap = int(total_income * FURUSATO_CAP_RATE)
    eligible = min(donated, cap)
    deductible = eligible - rules.deductions.furusato_floor
    return max(deductible, 0)


def compute_deductions(
    deductions: DeductionInput, total_income: int, rules: TaxRules
) -> tuple[DeductionBreakdown, int]:
    """Calcula todas las 所得控除 y devuelve desglose + total.

    Args:
        deductions: Entradas crudas de deducciones.
        total_income: 合計所得金額 (necesario para 基礎控除 escalonado, pisos y topes).
        rules: Parametros fiscales del anio.

    Returns:
        Tupla `(breakdown, total)` con el desglose y la suma de 所得控除.
    """
    kiso = kiso_deduction(total_income, rules)
    medical = medical_deduction(
        deductions.medical_expenses,
        deductions.medical_reimbursement,
        total_income,
        rules,
    )
    life = life_insurance_deduction(deductions.life_insurance, rules)
    earthquake = earthquake_insurance_deduction(deductions.earthquake_insurance, rules)
    dependents = dependent_deduction(deductions.dependents)
    furusato = furusato_deduction(deductions.furusato, total_income, rules)
    other = (
        deductions.disability_deduction
        + deductions.widow_single_parent_deduction
        + deductions.working_student_deduction
        + (270_000 if deductions.ordinary_disability_self else 0)
    )

    breakdown = DeductionBreakdown(
        kiso=kiso,
        social_insurance=deductions.social_insurance,
        medical=medical,
        life_insurance=life,
        earthquake_insurance=earthquake,
        dependents=dependents,
        spouse=deductions.spouse_deduction,
        ideco=deductions.ideco,
        furusato=furusato,
        other=other,
        ordinary_disability_self=deductions.ordinary_disability_self,
    )
    total = (
        kiso
        + deductions.social_insurance
        + medical
        + life
        + earthquake
        + dependents
        + deductions.spouse_deduction
        + deductions.ideco
        + furusato
        + other
    )
    return breakdown, total
