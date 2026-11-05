"""Motor de recomendaciones fiscales (節税アドバイザー) — plan 08.

Analiza el estado fiscal REAL del contribuyente (el `FilingDraftResult` ya
calculado + el 住民税 + las sugerencias de 控除) y genera una lista PRIORIZADA de
recomendaciones accionables, cada una con su **ahorro estimado en yenes**
(separando 所得税 y 住民税 cuando aplica) y un **atajo al screen** que la resuelve.

Principios (research / plan 08):
    - NUNCA hardcodear el ahorro: cada cifra sale de un escenario "qué pasaría si"
      recalculado con el MISMO motor (`calculate` / `calculate_resident_tax`), de
      modo que respeta el tramo marginal real, los pisos/topes y el redondeo.
    - NO duplica el cálculo del 所得税 ni del 住民税: reusa el `FilingDraftResult`
      (que ya trae ambos) y, para los escenarios hipotéticos, vuelve a invocar el
      motor con la 控除 hipotética agregada.
    - Honestidad: no somos 税理士. Cada ahorro va marcado como 概算 (estimación).

El motor consolida y EXTIENDE la detección proactiva de `/deductions/suggestions`
(no la duplica): toma esas sugerencias como insumo y las envuelve en el modelo
unificado de `Recommendation`, sumando las recomendaciones de mayor impacto que
requieren un escenario hipotético (老人扶養, 住宅ローン控除, 損益通算).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from app.domain.tax.deduction_service import deductions_to_input
from app.domain.tax.dependents import DEPENDENT_AMOUNTS
from app.domain.tax.income_tax import calculate
from app.domain.tax.resident_tax import calculate_resident_tax
from app.domain.tax.schemas import (
    Dependent,
    DependentKind,
    IncomeInput,
    TaxCalculationInput,
    WithholdingInput,
)
from app.models.enums import DeductionType
from app.services.forms.drafting import FilingDraftResult
from app.services.tax_rules import TaxRules

logger = logging.getLogger(__name__)

# 住民税 marginal del 所得割 (県4% + 市6% = 10%). Se usa para estimar el ahorro
#住民税 de una deducción que el motor de 住民税 reusa con su propio monto (扶養).
RESIDENT_TAX_MARGINAL_RATE = 0.10

# Tope orientativo de ふるさと納税 ≈ 住民税所得割 × 20% / (90% − 所得税率×1.021) + ¥2,000.
# Como la fórmula exacta depende del 所得税率 marginal y es 概算, usamos la
# aproximación estándar más conservadora basada en el 住民税所得割 (research 07).


class RecommendationCategory(StrEnum):
    """Categoría de una recomendación (para agrupar/iconografía en la UI)."""

    SETSUZEI = "setsuzei"  # 節税: oportunidad de pagar menos
    KOSEI = "kosei"  # 更正の請求: recuperar plata ya perdida
    INFO = "info"  # aviso / confirmación (損益通算 bien aprovechado, etc.)


class RecommendationPriority(StrEnum):
    """Prioridad de una recomendación (orden de presentación)."""

    HIGH = "alta"
    MEDIUM = "media"
    LOW = "baja"


class RecommendationStatus(StrEnum):
    """Estado de una recomendación respecto del contribuyente."""

    ACTIONABLE = "actionable"  # aplicable: hay plata por ganar/recuperar
    APPLIED = "applied"  # ya aplicado (confirmación)
    NEEDS_INFO = "needs_info"  # requiere que el usuario ingrese un dato


# Orden de presentación: alta -> media -> baja (clave de sort estable).
_PRIORITY_ORDER: dict[RecommendationPriority, int] = {
    RecommendationPriority.HIGH: 0,
    RecommendationPriority.MEDIUM: 1,
    RecommendationPriority.LOW: 2,
}


@dataclass(frozen=True)
class Recommendation:
    """Una recomendación fiscal accionable (ya calculada del estado real).

    Args:
        id: Identificador estable (en inglés) de la recomendación.
        category: Categoría (節税 / 更正の請求 / aviso).
        title_jp: Título en japonés (lo que ve el usuario).
        body_jp: Explicación pedagógica en japonés.
        body_es: Ayuda en español (rioplatense) para el owner.
        income_tax_saving: Ahorro estimado de 所得税 (+復興税) en yenes (概算).
        resident_tax_saving: Ahorro estimado de 住民税 en yenes (概算).
        total_saving: Ahorro total estimado (所得税 + 住民税) en yenes (概算).
        priority: Prioridad (alta / media / baja).
        status: Estado (aplicable / ya aplicado / requiere dato).
        action_label: Etiqueta del botón de acción (japonés).
        action_route: Id del screen destino (atajo). ``None`` si no hay atajo.
        is_estimate: ``True`` si el ahorro es 概算 (siempre lo es: no somos 税理士).
    """

    id: str
    category: RecommendationCategory
    title_jp: str
    body_jp: str
    body_es: str
    income_tax_saving: int
    resident_tax_saving: int
    total_saving: int
    priority: RecommendationPriority
    status: RecommendationStatus
    action_label: str
    action_route: str | None = None
    is_estimate: bool = True


@dataclass
class RecommendationReport:
    """Reporte completo del motor de recomendaciones de un 年度.

    Args:
        year: Año fiscal analizado.
        recommendations: Recomendaciones priorizadas (alta -> baja, ahorro desc).
        total_estimated_saving: Σ del ahorro de las recomendaciones ACCIONABLES
            (excluye las ya aplicadas / informativas, para no inflar la cifra).
        actionable_count: Nro de recomendaciones accionables (con plata por ganar).
    """

    year: int
    recommendations: list[Recommendation] = field(default_factory=list)
    total_estimated_saving: int = 0
    actionable_count: int = 0


def _owner_income_inputs(draft: FilingDraftResult) -> list[dict[str, Any]]:
    """Reconstruye los `incomes` del owner para los escenarios hipotéticos.

    El efecto de AGREGAR una 控除 depende solo del 合計所得金額 (ya consolidado tras
    el 損益通算), no del desglose por fuente: por eso el escenario "qué pasaría si"
    se modela con un único `jigyo` cuyo `amount` es el `total_income` REAL del
    draft. Así se reproduce EXACTAMENTE el mismo 合計所得 (jigyo pasa el monto tal
    cual; `total_income` ya es >= 0, sin más 損益通算) sin re-derivar cada 所得
    (re-feedear el 給与所得 NETO como `revenue` haría que el motor le reaplicara el
    給与所得控除 — bug evitado).

    Args:
        draft: Resultado del `build_filing_draft` (estado fiscal real).

    Returns:
        Lista con un único dict `IncomeInput`-compatible que reproduce el 合計所得.
    """
    return [{"kind": "jigyo", "amount": draft.tax.total_income}]


def _registered_types(draft: FilingDraftResult) -> set[DeductionType]:
    """Tipos de 控除 ya registrados (normalizados desde el str crudo de SQLite)."""
    types: set[DeductionType] = set()
    for ded in draft.deductions:
        raw = ded.type
        if isinstance(raw, DeductionType):
            types.add(raw)
            continue
        try:
            types.add(DeductionType(getattr(raw, "value", raw)))
        except ValueError:
            continue
    return types


def _has_dependents(draft: FilingDraftResult) -> bool:
    """``True`` si ya hay al menos un 扶養親族 que aporta 控除 registrado."""
    deduction_input = deductions_to_input(draft.deductions, year=draft.year)
    return len(deduction_input.dependents) > 0


def _elderly_dependent_saving(
    draft: FilingDraftResult, rules: TaxRules
) -> tuple[int, int]:
    """Estima el ahorro (所得税, 住民税) de AGREGAR un 老人扶養親族 別居.

    Escenario "qué pasaría si": recalcula el 所得税 y el 住民税 del owner con un
    扶養親族 老人別居 (¥480k 所得税 / ¥380k 住民税) agregado a las 控除 actuales,
    reusando el MISMO motor. La diferencia contra el cálculo real es el ahorro.

    Args:
        draft: Estado fiscal real del owner.
        rules: Parámetros fiscales del año.

    Returns:
        Tupla ``(ahorro_所得税, ahorro_住民税)`` en yenes (>= 0).
    """
    incomes = _owner_income_inputs(draft)
    base_input = deductions_to_input(draft.deductions, year=draft.year)

    # Escenario hipotético: misma base + un 老人扶養親族 別居.
    hypo_input = base_input.model_copy(
        update={"dependents": [*base_input.dependents, Dependent(kind=DependentKind.ELDERLY)]}
    )

    withholding = WithholdingInput(
        withholding_tax=draft.tax.withholding_total
    )
    tax_credits = draft.tax.tax_credits

    tax_base = calculate(
        TaxCalculationInput(
            year=draft.year,
            filing_type=draft.filing_type,
            incomes=cast(list[IncomeInput], incomes),
            deductions=base_input,
            withholding=withholding,
            tax_credits=tax_credits,
        ),
        rules,
    )
    tax_hypo = calculate(
        TaxCalculationInput(
            year=draft.year,
            filing_type=draft.filing_type,
            incomes=cast(list[IncomeInput], incomes),
            deductions=hypo_input,
            withholding=withholding,
            tax_credits=tax_credits,
        ),
        rules,
    )
    income_tax_saving = max(tax_base.total_tax - tax_hypo.total_tax, 0)

    resident_base = calculate_resident_tax(tax_base, base_input.dependents, rules)
    resident_hypo = calculate_resident_tax(tax_hypo, hypo_input.dependents, rules)
    resident_tax_saving = max(resident_base.total - resident_hypo.total, 0)

    return income_tax_saving, resident_tax_saving


def _build_elderly_dependent_recommendation(
    draft: FilingDraftResult, rules: TaxRules
) -> Recommendation | None:
    """Recomendación de registrar a un 老人扶養親族 別居 (ejemplo hipotético).

    Solo se genera si el owner NO tiene 扶養親族 registrados (si ya los tiene,
    asumimos que están contemplados). El ahorro se calcula con el escenario real.

    Args:
        draft: Estado fiscal real del owner.
        rules: Parámetros fiscales del año.

    Returns:
        La `Recommendation` o ``None`` si no aplica (ya hay 扶養) o no hay ahorro.
    """
    if _has_dependents(draft):
        return None
    income_tax_saving, resident_tax_saving = _elderly_dependent_saving(draft, rules)
    if income_tax_saving <= 0 and resident_tax_saving <= 0:
        return None
    fuyo_income, fuyo_resident = DEPENDENT_AMOUNTS[DependentKind.ELDERLY]
    return Recommendation(
        id="register_elderly_dependent",
        category=RecommendationCategory.KOSEI,
        title_jp="ご家族（老人扶養親族・別居）を扶養に追加",
        body_jp=(
            "70歳以上の親などを扶養（別居）に追加すると、所得税の課税所得が"
            f"{fuyo_income:,}円、住民税が{fuyo_resident:,}円減ります。"
            "生計を一にしていることなどの要件と、その年の所得・申告状況を確認してください。"
        ),
        body_es=(
            "Si mantienes a un familiar elegible de 70 años o más que vive aparte, "
            "considera 老人扶養 別居: "
            f"baja tu base de 所得税 en ¥{fuyo_income:,} y la de 住民税 en ¥{fuyo_resident:,}. "
            "Es un escenario hipotético: comprueba los requisitos, el año y si ya se declaró. "
            "Para años anteriores, revisa si procede una corrección."
        ),
        income_tax_saving=income_tax_saving,
        resident_tax_saving=resident_tax_saving,
        total_saving=income_tax_saving + resident_tax_saving,
        priority=RecommendationPriority.HIGH,
        status=RecommendationStatus.ACTIONABLE,
        action_label="更正の請求ガイドへ",
        action_route="kosei-seikyu",
    )


def _build_housing_loan_recommendation(
    draft: FilingDraftResult,
) -> Recommendation | None:
    """Recomendación sobre el 住宅ローン控除 (住宅借入金等特別控除).

    Si el owner YA tiene el 住宅ローン控除 aprobado (en `draft.tax.tax_credits`),
    se emite una CONFIRMACIÓN (status applied). Si NO lo tiene, se pide revisar
    primero el motivo del rechazo y la elegibilidad antes de un 更正の請求.

    Args:
        draft: Estado fiscal real del owner.

    Returns:
        La `Recommendation` correspondiente (confirmación o recuperación).
    """
    applied_credit = draft.tax.tax_credits
    if applied_credit > 0:
        return Recommendation(
            id="housing_loan_applied",
            category=RecommendationCategory.INFO,
            title_jp="税額控除の内訳を確認",
            body_jp=(
                f"税額控除として{applied_credit:,}円が登録されています。"
                "内訳は識別できないため、住宅ローン控除が含まれるか確認してください。"
            ),
            body_es=(
                f"Hay ¥{applied_credit:,} registrados como créditos fiscales. "
                "La app no identifica si incluyen el 住宅ローン控除; revisa el detalle."
            ),
            income_tax_saving=applied_credit,
            resident_tax_saving=0,
            total_saving=applied_credit,
            priority=RecommendationPriority.LOW,
            status=RecommendationStatus.APPLIED,
            action_label="申告内容を見る",
            action_route="filing",
        )
    return Recommendation(
        id="recover_housing_loan",
        category=RecommendationCategory.KOSEI,
        title_jp="住宅ローン控除の不承認理由を確認",
        body_jp=(
            "住宅借入金等特別控除は現在適用されていません。不承認通知で理由を確認し、"
            "適用要件を満たしていて書類不足だけが理由の場合に、更正の請求を検討します。"
            "適用不可の場合は請求額に含めません。"
        ),
        body_es=(
            "No hay un crédito fiscal registrado en este cálculo. Primero revisa "
            "el motivo oficial: si cumples los requisitos y solo faltaron documentos, puedes "
            "pedir una correccion; si la vivienda no es elegible, no debe reclamarse."
        ),
        income_tax_saving=0,
        resident_tax_saving=0,
        total_saving=0,
        priority=RecommendationPriority.HIGH,
        status=RecommendationStatus.NEEDS_INFO,
        action_label="更正の請求ガイドへ",
        action_route="kosei-seikyu",
    )


def _build_loss_offset_recommendation(
    draft: FilingDraftResult,
) -> Recommendation | None:
    """Confirmación del 損益通算 (la pérdida del 副業 compensa el 給与).

    Solo se emite si el 事業所得 es NEGATIVO (赤字) y hay otra fuente de ingreso
    (típicamente 給与) contra la cual compensar: en ese caso el 損益通算 ya está
    bien aprovechado y conviene confirmárselo al usuario.

    Args:
        draft: Estado fiscal real del owner.

    Returns:
        La `Recommendation` informativa o ``None`` si no hay pérdida que compensar.
    """
    if draft.business_income >= 0:
        return None
    has_other_income = any(
        item.kind != "jigyo" and item.amount > 0
        for item in draft.tax.income_breakdown
    )
    if not has_other_income:
        return None
    loss = abs(draft.business_income)
    return Recommendation(
        id="loss_offset_applied",
        category=RecommendationCategory.INFO,
        title_jp="事業所得の赤字を概算に反映",
        body_jp=(
            f"事業所得として入力された赤字 約{loss:,}円を他の所得と通算して概算しています。"
            "所得区分と経費の適否を確認してください。還付の有無は源泉徴収等を含めた計算によります。"
        ),
        body_es=(
            f"La estimación considera una pérdida de ¥{loss:,} registrada como 事業所得. "
            "Revisa la clasificación y los gastos admisibles; la devolución depende también "
            "de las retenciones y otros datos registrados."
        ),
        income_tax_saving=0,
        resident_tax_saving=0,
        total_saving=0,
        priority=RecommendationPriority.MEDIUM,
        status=RecommendationStatus.APPLIED,
        action_label="収入・経費を見る",
        action_route="income",
    )


def _build_furusato_recommendation(
    draft: FilingDraftResult,
    registered: set[DeductionType],
) -> Recommendation | None:
    """Recomendación de ふるさと納税 con tope orientativo por el 住民税所得割.

    Solo se sugiere si el owner aún NO declaró ふるさと納税 y tiene 住民税所得割 > 0
    (si no paga 住民税, no hay tope que aprovechar). El tope es 概算.

    Args:
        draft: Estado fiscal real del owner.
        registered: Tipos de 控除 ya registrados.

    Returns:
        La `Recommendation` o ``None`` si ya la usa o no hay 住民税所得割.
    """
    if DeductionType.FURUSATO in registered:
        return None
    shotokuwari = draft.resident_tax.shotokuwari_total
    if shotokuwari <= 0:
        return None
    return Recommendation(
        id="furusato_nozei",
        category=RecommendationCategory.SETSUZEI,
        title_jp="ふるさと納税の活用",
        body_jp=(
            "ふるさと納税の控除上限は所得・控除等によって変わります。"
            "寄附前に自治体などの計算ツールで条件を確認してください。"
        ),
        body_es=(
            "El límite depende de tus ingresos y deducciones. Antes de donar, "
            "comprueba las condiciones y el límite con una calculadora municipal."
        ),
        income_tax_saving=0,
        resident_tax_saving=0,
        total_saving=0,
        priority=RecommendationPriority.MEDIUM,
        status=RecommendationStatus.NEEDS_INFO,
        action_label="控除ウィザードへ",
        action_route="deduction-wizard",
    )


def _wrap_suggestion(
    suggestion_type: str,
    label: str,
    reason: str,
    estimated_saving: int | None,
) -> Recommendation:
    """Envuelve una sugerencia de `/deductions/suggestions` en una `Recommendation`.

    Consolida (no duplica) la detección proactiva de 控除: las sugerencias de
    医療費 / iDeCo / 社会保険 / 生命保険 ya calculadas se reexponen en el modelo
    unificado, con su atajo al 控除ウィザード.

    Args:
        suggestion_type: Tipo de 控除 sugerido (valor de `DeductionType`).
        label: Título japonés de la sugerencia.
        reason: Explicación japonesa de la sugerencia.
        estimated_saving: Ahorro estimado (所得税) o ``None`` si depende del monto.

    Returns:
        La `Recommendation` equivalente.
    """
    saving = estimated_saving or 0
    has_saving = saving > 0
    return Recommendation(
        id=f"deduction_{suggestion_type}",
        category=RecommendationCategory.SETSUZEI,
        title_jp=label,
        body_jp=reason,
        body_es=(
            "Oportunidad de 控除 detectada por la app. Cargá el comprobante en el "
            "控除ウィザード para aplicarla y bajar tu impuesto (ahorro 概算)."
        ),
        income_tax_saving=saving,
        resident_tax_saving=0,
        total_saving=saving,
        priority=(
            RecommendationPriority.MEDIUM if has_saving else RecommendationPriority.LOW
        ),
        status=(
            RecommendationStatus.ACTIONABLE if has_saving else RecommendationStatus.NEEDS_INFO
        ),
        action_label="控除ウィザードへ",
        action_route="deduction-wizard",
    )


def _sort_key(rec: Recommendation) -> tuple[int, int]:
    """Clave de orden: prioridad (alta->baja) y luego ahorro total descendente."""
    return (_PRIORITY_ORDER[rec.priority], -rec.total_saving)


def build_recommendations(
    draft: FilingDraftResult,
    suggestions: list[dict[str, Any]],
    rules: TaxRules,
) -> RecommendationReport:
    """Genera el reporte priorizado de recomendaciones fiscales del owner.

    Analiza el estado fiscal REAL (el `FilingDraftResult` con 所得税 + 住民税 ya
    calculados) + las sugerencias de 控除 y produce las recomendaciones de mayor
    impacto, cada una con su ahorro estimado (concreto, vía escenario "qué pasaría
    si" recalculado con el mismo motor) y su atajo al screen que la resuelve.

    Args:
        draft: Resultado del `build_filing_draft` (estado fiscal real del año).
        suggestions: Sugerencias de `/deductions/suggestions` (dicts con `type`,
            `label`, `reason`, `estimated_saving`). Se consolidan, no se duplican.
        rules: Parámetros fiscales del año.

    Returns:
        `RecommendationReport` con las recomendaciones priorizadas y el ahorro
        total estimado de las accionables.
    """
    registered = _registered_types(draft)
    recommendations: list[Recommendation] = []

    elderly = _build_elderly_dependent_recommendation(draft, rules)
    if elderly is not None:
        recommendations.append(elderly)

    housing = _build_housing_loan_recommendation(draft)
    if housing is not None:
        recommendations.append(housing)

    loss_offset = _build_loss_offset_recommendation(draft)
    if loss_offset is not None:
        recommendations.append(loss_offset)

    furusato = _build_furusato_recommendation(draft, registered)
    if furusato is not None:
        recommendations.append(furusato)

    # Consolidar las sugerencias de 控除 (医療費/iDeCo/社会保険/生命保険…). No se
    # vuelve a generar la de ふるさと納税 (ya se generó arriba con su tope propio).
    for suggestion in suggestions:
        s_type = suggestion.get("type")
        if s_type == DeductionType.FURUSATO.value:
            continue
        recommendations.append(
            _wrap_suggestion(
                suggestion_type=str(s_type),
                label=str(suggestion.get("label", "")),
                reason=str(suggestion.get("reason", "")),
                estimated_saving=suggestion.get("estimated_saving"),
            )
        )

    recommendations.sort(key=_sort_key)

    actionable = [
        r for r in recommendations if r.status == RecommendationStatus.ACTIONABLE
    ]
    total_saving = sum(r.total_saving for r in actionable)

    logger.info(
        "Recomendaciones year=%s -> %d (accionables=%d, ahorro=%s)",
        draft.year,
        len(recommendations),
        len(actionable),
        total_saving,
    )

    return RecommendationReport(
        year=draft.year,
        recommendations=recommendations,
        total_estimated_saving=total_saving,
        actionable_count=len(actionable),
    )
