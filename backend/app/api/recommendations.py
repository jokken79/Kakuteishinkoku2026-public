"""Router del motor de recomendaciones fiscales (節税アドバイザー) — plan 08.

Endpoint (bajo `/api/v1`):

- ``GET /recommendations/{year}`` — analiza el estado fiscal REAL del año (el
  `FilingDraft` con 所得税 + 住民税 ya calculados) + la detección proactiva de
  控除, y devuelve una lista PRIORIZADA de recomendaciones accionables, cada una
  con su ahorro estimado en yenes (所得税 / 住民税 / total, marcado 概算) y un atajo
  al screen que la resuelve.

El motor (`app.domain.recommendations`) es lógica pura: NO recalcula el 所得税 ni
el 住民税 (reusa el `FilingDraftResult`), y para los escenarios "qué pasaría si"
(ej. agregar a la mamá como 老人扶養) vuelve a invocar el MISMO motor. Este router
solo orquesta: arma el draft, junta las sugerencias de 控除 y serializa.

⚠️ No somos 税理士: cada ahorro es 概算 (estimación). La app es de apoyo.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deductions import deductions_suggestions
from app.db.session import get_db
from app.domain.recommendations import Recommendation, build_recommendations
from app.services.forms.drafting import build_filing_draft
from app.services.tax_rules import load_tax_rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


# --- Schemas de respuesta -------------------------------------------------


class RecommendationOut(BaseModel):
    """Una recomendación fiscal accionable serializada para la API.

    Args:
        id: Identificador estable de la recomendación.
        category: Categoría (``setsuzei`` / ``kosei`` / ``info``).
        title_jp: Título en japonés.
        body_jp: Explicación pedagógica en japonés.
        body_es: Ayuda en español.
        income_tax_saving: Ahorro estimado de 所得税 (¥, 概算).
        resident_tax_saving: Ahorro estimado de 住民税 (¥, 概算).
        total_saving: Ahorro total estimado (¥, 概算).
        priority: Prioridad (``alta`` / ``media`` / ``baja``).
        status: Estado (``actionable`` / ``applied`` / ``needs_info``).
        action_label: Etiqueta del botón de acción.
        action_route: Id del screen destino (atajo) o ``None``.
        is_estimate: ``True`` si el ahorro es 概算 (siempre).
    """

    id: str
    category: str
    title_jp: str
    body_jp: str
    body_es: str
    income_tax_saving: int
    resident_tax_saving: int
    total_saving: int
    priority: str
    status: str
    action_label: str
    action_route: str | None = None
    is_estimate: bool = True


class RecommendationReportOut(BaseModel):
    """Respuesta de `GET /recommendations/{year}`.

    Args:
        year: Año fiscal analizado.
        recommendations: Recomendaciones priorizadas (alta -> baja, ahorro desc).
        total_estimated_saving: Σ del ahorro de las accionables (¥, 概算).
        actionable_count: Nro de recomendaciones accionables.
    """

    year: int
    recommendations: list[RecommendationOut]
    total_estimated_saving: int
    actionable_count: int = Field(ge=0)


# --- Helpers --------------------------------------------------------------


def _to_out(rec: Recommendation) -> RecommendationOut:
    """Serializa una `Recommendation` del dominio a `RecommendationOut`."""
    return RecommendationOut(
        id=rec.id,
        category=rec.category.value,
        title_jp=rec.title_jp,
        body_jp=rec.body_jp,
        body_es=rec.body_es,
        income_tax_saving=rec.income_tax_saving,
        resident_tax_saving=rec.resident_tax_saving,
        total_saving=rec.total_saving,
        priority=rec.priority.value,
        status=rec.status.value,
        action_label=rec.action_label,
        action_route=rec.action_route,
        is_estimate=rec.is_estimate,
    )


# --- Endpoint -------------------------------------------------------------


@router.get("/{year}", response_model=RecommendationReportOut)
def get_recommendations(
    year: int,
    db: Session = Depends(get_db),
) -> RecommendationReportOut:
    """Genera las recomendaciones fiscales priorizadas del año.

    Arma el `FilingDraft` (estado fiscal real con 所得税 + 住民税), junta las
    sugerencias de 控除 y delega al motor de recomendaciones, que calcula cada
    ahorro con un escenario "qué pasaría si" recalculado con el mismo motor.

    Args:
        year: 年度 (令和7 = 2025).
        db: Sesión de BD.

    Returns:
        `RecommendationReportOut` con las recomendaciones priorizadas y el ahorro
        total estimado de las accionables.

    Raises:
        HTTPException: 400 si el año no tiene parámetros; 404 si no hay 年度.
    """
    try:
        rules = load_tax_rules(year)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unsupported_fiscal_year",
                "message": f"{year}年の税制パラメータがありません。",
                "details": {"year": year},
            },
        ) from exc

    # Proyectar en un SAVEPOINT y revertirlo: el GET no guarda ni borra asientos.
    savepoint = db.begin_nested()
    try:
        try:
            draft = build_filing_draft(
                db, year, rules=rules, persist=False, preview_projection=True,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "no_fiscal_year",
                    "message": f"{year}年度が見つかりませんでした。",
                    "details": {"year": year},
                },
            ) from exc

        suggestions = deductions_suggestions(year=year, db=db)
        suggestion_dicts = [s.model_dump() for s in suggestions]
        report = build_recommendations(draft, suggestion_dicts, rules)
        return RecommendationReportOut(
            year=report.year,
            recommendations=[_to_out(r) for r in report.recommendations],
            total_estimated_saving=report.total_estimated_saving,
            actionable_count=report.actionable_count,
        )
    finally:
        savepoint.rollback()
