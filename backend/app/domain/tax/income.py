"""Calculo de cada uno de los 所得 (research 01 §2).

Cada funcion recibe los campos crudos de una `IncomeInput` y devuelve el
所得金額 (entero, JPY). Solo se modela tributacion **global** (総合課税); la
separacion vs 申告分離課税 se refleja en que los tipos de tasa fija no se incluyen.
"""

import logging

from app.domain.tax.schemas import (
    IncomeBreakdownItem,
    IncomeInput,
    IncomeKind,
)
from app.services.tax_rules import TaxRules

logger = logging.getLogger(__name__)

# 特別控除 del 一時所得 (¥500,000) — constante legal, no parametrizada por anio.
ICHIJI_SPECIAL_DEDUCTION = 500_000


def salary_income(revenue: int, rules: TaxRules) -> int:
    """Calcula el 給与所得 = 収入 − 給与所得控除 (令和7).

    Usa la **tabla oficial 給与所得控除後の金額** del 国税庁 (令和2年分以降): para el
    収入 entre ¥1,625,001 y ¥6,599,999 el 収入金額 se **cuantiza a múltiplos de
    ¥4,000** (``A = 収入 // 4000``) ANTES de aplicar el factor del tramo. Esto NO es
    cosmético: la fórmula directa (``収入 × 0.2 + 440,000``) difiere de la tabla
    oficial hasta en ~¥3,000 de 課税所得. El cálculo oficial usa el 収入 cuantizado.

    Tabla 給与所得控除後の金額 令和7年 (``A = 収入 // 4000``):
        ≤ ¥1,625,000      -> 給与所得 = 収入 − ¥650,000 (控除 mínimo)
        ≤ ¥1,800,000      -> A×4000 × 0.6 + ¥100,000
        ≤ ¥3,600,000      -> A×4000 × 0.7 − ¥80,000
        ≤ ¥6,600,000      -> A×4000 × 0.8 − ¥440,000
        ≤ ¥8,500,000      -> 収入 × 0.9 − ¥1,100,000
        > ¥8,500,000      -> 収入 − ¥1,950,000 (tope del 控除)

    El piso del 控除 (¥650,000, `salary_deduction_min`) se respeta vía el tramo bajo.

    Args:
        revenue: 給与収入金額 bruto.
        rules: Parametros fiscales del anio.

    Returns:
        給与所得金額 (>= 0).
    """
    if revenue <= 0:
        return 0

    floor = rules.salary_deduction_min  # ¥650,000 en 令和7.
    # NTA 令和8・9: tabla especial antes de aplicar los intervalos de ¥4,000.
    # https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1410.htm
    if rules.year in (2026, 2027) and revenue < 2_200_000:
        if revenue < 741_000:
            return 0
        if revenue < 2_191_000:
            return revenue - floor
        if revenue < 2_193_000:
            return 1_451_000
        if revenue < 2_196_000:
            return 1_453_000
        return 1_456_000
    if revenue <= 1_625_000:
        # Tramo del 控除 mínimo: 給与所得 = 収入 − piso (no baja de 0).
        return max(revenue - floor, 0)

    if revenue <= 6_600_000:
        # 収入 cuantizado a ¥4,000 (別表第五: 給与所得控除後の金額). El 給与所得 sale
        # directo de la tabla (no como 収入 − 控除); por eso difiere de la fórmula
        # directa hasta en ~¥2,000 de 所得. Se acota con `min(…, 収入 − piso)`
        # para respetar el piso del 控除 (¥650,000) cuando el 控除 calculado es menor,
        # rige el piso (p. ej. 収入 ¥1,800,000 → 給与所得 ¥1,150,000).
        quantized = (revenue // 4_000) * 4_000
        if revenue <= 1_800_000:
            shotoku = int(quantized * 0.6) + 100_000
        elif revenue <= 3_600_000:
            shotoku = int(quantized * 0.7) - 80_000
        else:  # ≤ ¥6,600,000
            shotoku = int(quantized * 0.8) - 440_000
        return max(min(shotoku, revenue - floor), 0)

    # Tramos altos (> ¥6,600,000): la fórmula directa coincide con la tabla.
    if revenue <= 8_500_000:
        deduction = int(revenue * 0.1) + 1_100_000
    else:
        deduction = 1_950_000
    deduction = min(deduction, revenue)
    return max(revenue - deduction, 0)


def business_income(amount: int) -> int:
    """Devuelve el 事業所得 (ya neto = PL − 青色申告特別控除).

    El motor contable (LANE A) entrega este monto calculado; aca solo se pasa.

    Args:
        amount: 事業所得金額 ya neto.

    Returns:
        事業所得金額 (puede ser negativo en caso de perdida; se respeta el signo).
    """
    return amount


def miscellaneous_income(revenue: int, expenses: int) -> int:
    """Calcula el 雑所得 = 収入 − 必要経費 (no baja de 0).

    Args:
        revenue: 収入金額.
        expenses: 必要経費.

    Returns:
        雑所得金額 (>= 0).
    """
    return max(revenue - expenses, 0)


def real_estate_income(revenue: int, expenses: int) -> int:
    """Calcula el 不動産所得 = 収入 − 必要経費.

    Args:
        revenue: 収入金額.
        expenses: 必要経費.

    Returns:
        不動産所得金額 (se respeta el signo: puede dar perdida).
    """
    return revenue - expenses


def temporary_income(revenue: int, expenses: int) -> int:
    """Calcula el 一時所得 = (収入 − 支出 − ¥500,000) × 1/2 (research 01 §2).

    El 特別控除 de ¥500,000 se aplica antes de partir por la mitad; si el neto es
    negativo, el 所得 es 0.

    Args:
        revenue: 収入金額.
        expenses: 支出金額.

    Returns:
        課税対象となる 一時所得金額 (>= 0).
    """
    net = revenue - expenses - ICHIJI_SPECIAL_DEDUCTION
    if net <= 0:
        return 0
    return net // 2


def dividend_income(amount: int) -> int:
    """Devuelve el 配当所得 (総合課税) ya neto.

    Args:
        amount: 配当所得金額 ya neto.

    Returns:
        配当所得金額.
    """
    return amount


def compute_income(item: IncomeInput, rules: TaxRules) -> int:
    """Despacha al calculo correcto segun el tipo de 所得.

    Args:
        item: Fuente de ingreso.
        rules: Parametros fiscales del anio.

    Returns:
        所得金額 (entero) de la fuente.
    """
    match item.kind:
        case IncomeKind.KYUYO:
            return salary_income(item.revenue, rules)
        case IncomeKind.JIGYO:
            return business_income(item.amount)
        case IncomeKind.ZATSU:
            return miscellaneous_income(item.revenue, item.expenses)
        case IncomeKind.FUDOSAN:
            return real_estate_income(item.revenue, item.expenses)
        case IncomeKind.ICHIJI:
            return temporary_income(item.revenue, item.expenses)
        case IncomeKind.HAITO:
            return dividend_income(item.amount)
        case _:
            raise ValueError(f"Tipo de 所得 no soportado: {item.kind}")


# Tipos de 所得 cuya PERDIDA (赤字) se compensa contra los demas 総合課税 所得 —
# 損益通算可能 (research 01 §2: 事業 / 不動産 / 譲渡 / 山林). En este MVP modelamos
# 事業 y 不動産 (los unicos que pueden dar perdida en la calculadora global). El
# resto de las categorias (給与 / 雑 / 一時 / 配当) NO genera perdida deducible:
# su 所得 ya viene acotado a >= 0 desde su propio calculo.
LOSS_OFFSETTABLE_KINDS: frozenset[IncomeKind] = frozenset(
    {IncomeKind.JIGYO, IncomeKind.FUDOSAN}
)


def compute_all_incomes(
    incomes: list[IncomeInput], rules: TaxRules
) -> tuple[list[IncomeBreakdownItem], int]:
    """Calcula todos los 所得 y su suma con 損益通算 (合計所得金額, base global).

    Implementa el **損益通算** (research 01 §2): si el 事業所得 o el 不動産所得 es
    NEGATIVO (赤字), esa perdida se RESTA de los demas 総合課税 所得 (給与, 雑, …).
    Asi el caso real del owner — 給与 (principal) + 事業 (副業) en perdida — baja el
    課税所得 y puede generar 還付 del 源泉徴収 del sueldo.

    El 合計所得金額 resultante no baja de 0 (una perdida mayor que el resto de los
    ingresos del año se arrastra via 純損失の繰越 — fuera de scope de este MVP — no
    como base negativa).

    Args:
        incomes: Lista de fuentes de ingreso.
        rules: Parametros fiscales del anio.

    Returns:
        Tupla `(breakdown, total)` donde `breakdown` detalla cada 所得 (el signo de
        las perdidas 損益通算可能 se respeta para trazabilidad) y `total` es el
        合計所得金額 tras la compensacion (>= 0).
    """
    breakdown: list[IncomeBreakdownItem] = []
    positive_total = 0  # Σ所得 de categorias que NO compensan perdida (o positivas).
    loss_offset = 0  # Σ perdidas de categorias 損益通算可能 (valor positivo a restar).
    salary_items = [item for item in incomes if item.kind == IncomeKind.KYUYO]
    salary_total = sum(item.revenue for item in salary_items)
    salary_processed = False
    temporary_items = [item for item in incomes if item.kind == IncomeKind.ICHIJI]
    temporary_processed = False

    for item in incomes:
        if item.kind == IncomeKind.KYUYO:
            if salary_processed:
                continue
            salary_processed = True
            amount = salary_income(salary_total, rules)
            label = item.label if len(salary_items) == 1 else "給与所得（合算）"
        elif item.kind == IncomeKind.ICHIJI:
            if temporary_processed:
                continue
            temporary_processed = True
            amount = temporary_income(
                sum(entry.revenue for entry in temporary_items),
                sum(entry.expenses for entry in temporary_items),
            )
            label = item.label if len(temporary_items) == 1 else "一時所得（合算）"
        else:
            amount = compute_income(item, rules)
            label = item.label
        breakdown.append(
            IncomeBreakdownItem(kind=item.kind, label=label, amount=amount)
        )
        if item.kind in LOSS_OFFSETTABLE_KINDS and amount < 0:
            # 赤字 de una categoria 損益通算可能: se acumula para restar del resto.
            loss_offset += -amount
        else:
            # Categoria positiva (o no compensable): suma normal. Las categorias
            # no compensables ya vienen >= 0 desde su propio calculo.
            positive_total += max(amount, 0) if item.kind not in LOSS_OFFSETTABLE_KINDS else amount

    # Una pérdida ordinaria compensa primero ingresos ordinarios; el remanente
    # reduce 一時所得 antes de computar la mitad. No aplicar la pérdida dos veces.
    temporary_net = max(
        sum(entry.revenue - entry.expenses for entry in temporary_items)
        - ICHIJI_SPECIAL_DEDUCTION,
        0,
    )
    ordinary_positive = positive_total - temporary_net // 2
    ordinary_after = max(ordinary_positive - loss_offset, 0)
    remaining_loss = max(loss_offset - ordinary_positive, 0)
    total = ordinary_after + max(temporary_net - remaining_loss, 0) // 2
    return breakdown, total
