"""Router del 扶養家族 (扶養控除 detallado + 国外居住) — research 08, 令和7.

Endpoints (bajo `/api/v1`):

- ``POST /dependents/classify`` — clasifica una lista de 扶養親族 SIN persistir:
  devuelve la categoria, el monto (所得税/住民税), si califica, y los documentos
  requeridos (国外居住). El frontend lo usa para mostrar EN VIVO "la app calcula
  sola la categoria y el monto" + el checklist de documentos.

Los 扶養親族 se PERSISTEN como una unica 控除 de tipo `fuyo` con la lista
estructurada en `meta.dependents` (ver `app.api.deductions`); aqui solo se expone
la clasificacion pura (`app.domain.tax.dependents`).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.domain.tax.dependents import (
    DependentResult,
    classify_dependents,
    dependent_income_threshold,
)
from app.domain.tax.schemas import DependentInput, DependentKind

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dependents"])

# Etiquetas japonesas de cada categoria (para la UI).
_KIND_LABEL: dict[DependentKind, str] = {
    DependentKind.GENERAL: "一般扶養親族",
    DependentKind.SPECIFIC: "特定扶養親族",
    DependentKind.ELDERLY: "老人扶養親族（同居老親等以外）",
    DependentKind.ELDERLY_COHABITING: "同居老親等",
    DependentKind.YOUNG: "年少扶養親族（16歳未満）",
    DependentKind.NONE: "対象外",
}

# Documentos requeridos (国外居住扶養親族): codigo -> (etiqueta JP, descripcion JP).
_DOC_LABELS: dict[str, dict[str, str]] = {
    "shinzoku_kankei": {
        "label": "親族関係書類",
        "description": "戸籍の附票やパスポート＋出生証明書など、親族関係を証明する書類。",
    },
    "soukin_kankei": {
        "label": "送金関係書類",
        "description": "その年に送金したことがわかる書類（送金明細・クレジットカード明細など）。",
    },
    "ryugaku_visa": {
        "label": "留学ビザ等書類",
        "description": "外国の査証（ビザ）など、留学を証明する書類。",
    },
    "soukin_38man": {
        "label": "38万円送金書類",
        "description": "その年に38万円以上を送金したことを証明する書類。",
    },
}

# Motivos de no-elegibilidad (clave -> mensaje JP).
_DISQUALIFIED_LABEL: dict[str, str] = {
    "jigyo_senju": "事業専従者は扶養控除の対象外です。",
    "income_over_threshold": "扶養親族の合計所得金額がその年の上限を超えています。",
    "income_unknown": (
        "合計所得金額が未入力のため、控除額を計算できません。0円の場合は0を入力してください。"
    ),
    "birth_date_unknown": "生年月日が未入力のため、扶養区分を確認できません。",
    "remittance_unknown": (
        "送金額が未入力です。この親族への年間送金額と証明書類を確認してください。"
    ),
    "remittance_below_380k": (
        "入力された年間送金額は38万円未満です。他の適用事由も確認してください。"
    ),
    "overseas_30_69_no_reason": (
        "国外居住で30〜69歳の場合、留学・障害者・年38万円以上の送金のいずれかがないと対象外です。"
    ),
}


# --- Schemas --------------------------------------------------------------


class DocumentRequirement(BaseModel):
    """Un documento requerido para un 国外居住扶養親族.

    Args:
        code: Clave estable del documento.
        label: Etiqueta japonesa.
        description: Descripcion japonesa de que se necesita.
    """

    code: str
    label: str
    description: str


class DependentClassification(BaseModel):
    """Resultado de clasificar un 扶養親族 (para la UI).

    Args:
        name: Nombre del familiar.
        kind: Categoria resuelta (clave).
        kind_label: Etiqueta japonesa de la categoria.
        age: Edad al 31/12 (o ``None``).
        income_tax_amount: 扶養控除 del 所得税 (¥).
        resident_tax_amount: 扶養控除 del 住民税 (¥).
        qualifies: ``True`` si aporta 控除 al 所得税.
        is_overseas: ``True`` si es 国外居住.
        required_documents: Documentos requeridos (国外居住).
        needs_translation: ``True`` si hace falta 翻訳文 (traduccion al japones).
        disqualified_reason: Motivo (clave) por el que no califica, o ``None``.
        disqualified_message: Mensaje japones del motivo, o ``None``.
    """

    name: str
    kind: DependentKind
    kind_label: str
    age: int | None
    income_tax_amount: int
    resident_tax_amount: int
    qualifies: bool
    is_overseas: bool
    required_documents: list[DocumentRequirement] = Field(default_factory=list)
    needs_translation: bool = False
    disqualified_reason: str | None = None
    disqualified_message: str | None = None


class DependentsClassifyOut(BaseModel):
    """Respuesta de `POST /dependents/classify`.

    Args:
        year: Año fiscal usado para calcular la edad al 31/12.
        dependents: Clasificacion de cada 扶養親族.
        total_income_tax_deduction: Σ 扶養控除 (所得税) de los que califican.
        total_resident_tax_deduction: Σ 扶養控除 (住民税) de los que califican.
        income_threshold: Umbral de 合計所得金額 del dependiente (令和7).
    """

    year: int
    dependents: list[DependentClassification]
    total_income_tax_deduction: int
    total_resident_tax_deduction: int
    income_threshold: int


# --- Helpers --------------------------------------------------------------


def _to_classification(result: DependentResult) -> DependentClassification:
    """Serializa un `DependentResult` a `DependentClassification`."""
    docs = [
        DocumentRequirement(
            code=code,
            label=_DOC_LABELS.get(code, {}).get("label", code),
            description=_DOC_LABELS.get(code, {}).get("description", ""),
        )
        for code in result.required_documents
    ]
    reason = result.disqualified_reason
    return DependentClassification(
        name=result.name,
        kind=result.kind,
        kind_label=(
            "要確認"
            if reason in {"income_unknown", "birth_date_unknown", "remittance_unknown"}
            else _KIND_LABEL.get(result.kind, result.kind.value)
        ),
        age=result.age,
        income_tax_amount=result.income_tax_amount,
        resident_tax_amount=result.resident_tax_amount,
        qualifies=result.qualifies,
        is_overseas=result.is_overseas,
        required_documents=docs,
        needs_translation=result.needs_translation,
        disqualified_reason=reason,
        disqualified_message=_DISQUALIFIED_LABEL.get(reason) if reason else None,
    )


# --- Endpoint -------------------------------------------------------------


@router.post("/dependents/classify", response_model=DependentsClassifyOut)
def classify_dependents_endpoint(
    dependents: list[DependentInput],
    year: int = Query(default=2025, ge=2020, le=2026),
) -> DependentsClassifyOut:
    """Clasifica 扶養親族 (categoria + monto + 国外 docs) sin persistir.

    Args:
        dependents: Datos crudos de los familiares a cargo.
        year: Año fiscal (令和7 = 2025) — para la edad al 31/12.

    Returns:
        `DependentsClassifyOut` con la clasificacion de cada uno y los totales.
    """
    results = classify_dependents(dependents, year)
    classifications = [_to_classification(r) for r in results]
    total_income = sum(r.income_tax_amount for r in results)
    total_resident = sum(r.resident_tax_amount for r in results)
    logger.info(
        "扶養 classify year=%s n=%d total_income_tax=%s",
        year,
        len(results),
        total_income,
    )
    return DependentsClassifyOut(
        year=year,
        dependents=classifications,
        total_income_tax_deduction=total_income,
        total_resident_tax_deduction=total_resident,
        income_threshold=dependent_income_threshold(year),
    )
