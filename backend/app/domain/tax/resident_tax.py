"""Calculo del 住民税 (impuesto de residencia) — estimacion 令和7 / 2025.

El 住民税 se liquida al **AÑO SIGUIENTE** (jun-may) y NO es un 還付: es un pago
futuro. Se calcula sobre un 課税所得 DISTINTO al del 所得税 porque las deducciones
difieren (research 住民税):

    - 基礎控除 住民税 = ¥430,000 (no ¥480k/¥580k del 所得税, no escalonado).
    - 扶養控除 住民税 menores (一般 ¥330k / 特定 ¥450k / 老人別居 ¥380k / 同居老親 ¥450k).
    - 社会保険料控除 / 医療費控除 / etc. = mismo monto real que el 所得税.
    - SIN 復興特別税 (eso es solo 所得税).

Estructura del 住民税::

    住民税 = 所得割 + 均等割 − 調整控除
    所得割 = 課税住民 × 10% (= 県民税 4% + 市民税 6%)
    均等割 = 県民税分 + 市民税分 + 森林環境税(¥1,000 国税)
    調整控除 = ajuste por la diferencia de 人的控除 (基礎/扶養…) entre 所得税 y 住民税.

⚠️ Estimacion: el 住民税 real lo liquida el 市区町村, no somos 税理士. Esta cifra
es orientativa para que el contribuyente vea el panorama fiscal completo.

Reusa el `TaxCalculationResult` ya calculado por el motor del 所得税 (NO recalcula
el 合計所得 ni las 控除 comunes): toma `total_income` y el `DeductionBreakdown`,
reemplaza SOLO el 基礎控除 y el 扶養控除 por sus montos del 住民税, y mantiene el
resto (社会保険/医療費/生命/地震/配偶者/iDeCo/寄附金/その他) tal cual.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.tax.dependents import DEPENDENT_AMOUNTS
from app.domain.tax.schemas import (
    Dependent,
    TaxCalculationResult,
)
from app.services.tax_rules import ResidentTaxRules, TaxRules

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResidentTaxResult:
    """Desglose del 住民税 estimado de un contribuyente.

    Args:
        year: Anio fiscal del calculo (el 住民税 se paga el anio siguiente).
        total_income: 合計所得金額 (reusado del calculo del 所得税).
        resident_deductions_total: Σ所得控除 del 住民税 (con 基礎/扶養 del 住民税).
        kiso_kojo: 基礎控除 住民税 aplicado (¥430,000 en 令和7).
        dependent_deduction: 扶養控除 住民税 total (suma por categoria).
        taxable_income: 課税所得(住民) redondeado a la baja al millar (>= 0).
        shotokuwari_prefectural: 所得割 県民税 (課税住民 × 4%).
        shotokuwari_municipal: 所得割 市民税 (課税住民 × 6%).
        shotokuwari_total: 所得割 total (県 + 市).
        kintowari_prefectural: 均等割 県民税.
        kintowari_municipal: 均等割 市民税.
        forest_environment_tax: 森林環境税 (¥1,000 国税).
        kintowari_total: 均等割 total (県 + 市 + 森林環境税).
        chosei_kojo: 調整控除 (ajuste por 人的控除差).
        total: 住民税 estimado = 所得割 + 均等割 − 調整控除 (>= 均等割).
    """

    year: int
    total_income: int
    resident_deductions_total: int
    kiso_kojo: int
    dependent_deduction: int
    taxable_income: int
    shotokuwari_prefectural: int
    shotokuwari_municipal: int
    shotokuwari_total: int
    kintowari_prefectural: int
    kintowari_municipal: int
    forest_environment_tax: int
    kintowari_total: int
    chosei_kojo: int
    total: int


def _round_down(amount: int, unit: int) -> int:
    """Redondea un monto a la baja al multiplo de `unit` (>= 0).

    Args:
        amount: Monto a redondear (puede ser negativo).
        unit: Unidad de redondeo (ej. ¥1,000).

    Returns:
        Monto redondeado a la baja (0 si era <= 0).
    """
    if amount <= 0:
        return 0
    return (amount // unit) * unit


def _resident_dependent_deduction(dependents: list[Dependent]) -> int:
    """Calcula el 扶養控除 del 住民税 sumando el monto住民税 por categoria.

    Usa el segundo elemento de `DEPENDENT_AMOUNTS[kind]` (= monto 住民税), que es
    DISTINTO al del 所得税 (一般 ¥330k vs ¥380k, 老人別居 ¥380k vs ¥480k, etc.).

    Args:
        dependents: Familiares a cargo (categoria ya resuelta).

    Returns:
        扶養控除 住民税 total.
    """
    return sum(DEPENDENT_AMOUNTS.get(d.kind, (0, 0))[1] for d in dependents)


def _chosei_kojo(
    taxable_income: int,
    dependents: list[Dependent],
    has_kiso: bool,
    rules: ResidentTaxRules,
    ordinary_disability_self: bool = False,
) -> int:
    """Calcula el 調整控除 (ajuste por la diferencia de 人的控除).

    El 調整控除 corrige que el 住民税 tenga 人的控除 (基礎/扶養/配偶者…) menores que
    el 所得税. Usa el **人的控除差** (tabla fija del 国税庁, NO la diferencia bruta
    escalonada). Formula (research 住民税 No.2):

        - 課税住民 <= ¥2,000,000: min(Σ人的控除差, 課税住民) × 5%.
        - 課税住民  > ¥2,000,000: max(Σ人的控除差 − (課税住民 − 200万), 5万) × 5%.

    Implementa solo los 人的控除差 del 基礎控除 y del 扶養控除 (los que el perfil del
    owner usa). 配偶者控除/障害者控除 等 quedan fuera de scope (el caso real no los
    tiene); si se agregan, parametrizar su 人的控除差 en `ResidentTaxRules`.

    Args:
        taxable_income: 課税所得(住民) ya redondeado.
        dependents: Familiares a cargo (para su 人的控除差 por categoria).
        has_kiso: ``True`` si aplica 基礎控除 (suma su 人的控除差 ¥50,000).
        rules: Parametros del 住民税.

    Returns:
        調整控除 (¥, >= 0).
    """
    if taxable_income <= 0:
        return 0
    diff_total = rules.chosei_kojo_basic_diff if has_kiso else 0
    diff_total += sum(rules.dependent_diff_for(d.kind.value) for d in dependents)
    if ordinary_disability_self:
        diff_total += 10_000
    if diff_total <= 0:
        return 0

    if taxable_income <= rules.chosei_kojo_threshold:
        base = min(diff_total, taxable_income)
        return int(base * rules.chosei_kojo_low_rate)
    # > umbral: formula reducida con piso de ¥50,000 (=> 調整控除 minimo ¥2,500).
    reduced = diff_total - (taxable_income - rules.chosei_kojo_threshold)
    base = max(reduced, rules.chosei_kojo_min * 20)  # 5万 = 2,500 / 0.05.
    return int(base * rules.chosei_kojo_low_rate)


def calculate_resident_tax(
    income_tax_result: TaxCalculationResult,
    dependents: list[Dependent],
    rules: TaxRules,
) -> ResidentTaxResult:
    """Estima el 住民税 a partir del resultado del 所得税 (logica pura).

    Reusa `income_tax_result.total_income` (合計所得) y su `deduction_breakdown`:
    mantiene las 控除 comunes (社会保険/医療費/生命/地震/配偶者/iDeCo/寄附金/その他)
    y reemplaza SOLO el 基礎控除 y el 扶養控除 por sus montos del 住民税. NO recalcula
    el 合計所得 (eso ya lo hizo el motor del 所得税).

    Args:
        income_tax_result: Resultado del calculo del 所得税 (`calculate()`).
        dependents: Familiares a cargo (categoria ya resuelta), para el 扶養控除
            del 住民税 y el 人的控除差 del 調整控除. Mismo orden que entro al 所得税.
        rules: Parametros fiscales del anio (`resident_tax`).

    Returns:
        `ResidentTaxResult` con el desglose completo del 住民税 estimado.
    """
    rt = rules.resident_tax
    breakdown = income_tax_result.deduction_breakdown
    total_income = income_tax_result.total_income

    kiso = rt.kiso_kojo
    has_kiso = total_income > 0  # 基礎控除 住民税 plano (合計所得 <= ¥24M); 0 si sin 所得.
    dependent_deduction = _resident_dependent_deduction(dependents)

    # Σ所得控除 住民税 = (Σ所得控除 所得税 − 基礎所得税 − 扶養所得税) + 基礎住民税 + 扶養住民税.
    # El resto de las 控除 (社会保険/医療費/生命/地震/配偶者/iDeCo/寄附金/その他) se
    # mantienen iguales al 所得税 (mismo monto real; el 住民税 reusa esos valores).
    common_deductions = (
        breakdown.social_insurance
        + breakdown.medical
        + breakdown.life_insurance
        + breakdown.earthquake_insurance
        + breakdown.spouse
        + breakdown.ideco
        + breakdown.furusato
        + breakdown.other
    )
    # La discapacidad ordinaria del titular deduce 27万 en renta y 26万 en 住民税.
    # Solo se convierte cuando está registrada explícitamente; OTHER es ambiguo.
    if breakdown.ordinary_disability_self:
        common_deductions -= 10_000
    resident_deductions_total = common_deductions + kiso + dependent_deduction

    raw_taxable = total_income - resident_deductions_total
    taxable_income = _round_down(raw_taxable, rt.taxable_rounding)

    shotokuwari_prefectural = int(taxable_income * rt.shotokuwari_prefectural_rate)
    shotokuwari_municipal = int(taxable_income * rt.shotokuwari_municipal_rate)
    shotokuwari_total = shotokuwari_prefectural + shotokuwari_municipal

    chosei = _chosei_kojo(
        taxable_income,
        dependents,
        has_kiso=has_kiso and taxable_income > 0,
        rules=rt,
        ordinary_disability_self=breakdown.ordinary_disability_self,
    )
    # El 調整控除 baja el 所得割; no puede dejarlo negativo.
    shotokuwari_after_chosei = max(shotokuwari_total - chosei, 0)

    kintowari_total = (
        rt.kintowari_prefectural + rt.kintowari_municipal + rt.forest_environment_tax
    )

    # 均等割 se cobra solo si hay 課税対象 (課税住民 > 0). Sin 所得 imponible, ni
    # 所得割 ni 均等割 (simplificacion: el 非課税限度額 real depende del 市区町村 y de
    # los 扶養; aca no estimamos exenciones — el caso del owner siempre supera el piso).
    if taxable_income <= 0:
        return ResidentTaxResult(
            year=income_tax_result.year,
            total_income=total_income,
            resident_deductions_total=resident_deductions_total,
            kiso_kojo=kiso,
            dependent_deduction=dependent_deduction,
            taxable_income=0,
            shotokuwari_prefectural=0,
            shotokuwari_municipal=0,
            shotokuwari_total=0,
            kintowari_prefectural=0,
            kintowari_municipal=0,
            forest_environment_tax=0,
            kintowari_total=0,
            chosei_kojo=0,
            total=0,
        )

    total = shotokuwari_after_chosei + kintowari_total

    return ResidentTaxResult(
        year=income_tax_result.year,
        total_income=total_income,
        resident_deductions_total=resident_deductions_total,
        kiso_kojo=kiso,
        dependent_deduction=dependent_deduction,
        taxable_income=taxable_income,
        shotokuwari_prefectural=shotokuwari_prefectural,
        shotokuwari_municipal=shotokuwari_municipal,
        shotokuwari_total=shotokuwari_total,
        kintowari_prefectural=rt.kintowari_prefectural,
        kintowari_municipal=rt.kintowari_municipal,
        forest_environment_tax=rt.forest_environment_tax,
        kintowari_total=kintowari_total,
        chosei_kojo=chosei,
        total=total,
    )
