"""Router del wizard de 控除 (所得控除) — Fase 3B-1.

Endpoints (bajo `/api/v1`):

- ``GET    /deductions?year=2025``             — lista las 控除 registradas + total.
- ``POST   /deductions``                        — crea una 控除 (type, amount, meta).
- ``PATCH  /deductions/{id}``                   — edita monto / meta.
- ``DELETE /deductions/{id}``                   — borra una 控除.
- ``GET    /deductions/summary?year=2025``      — breakdown + total aplicado a la
  calculadora (lee las 控除 reales, mapea -> DeductionInput, devuelve el efecto).
- ``GET    /deductions/suggestions?year=2025``  — deteccion proactiva de 控除 que el
  usuario podria estar perdiendo (medico, ふるさと納税, iDeCo, 社会保険, 生命保険).

Las 控除 viven en la entidad `Deduction` (una fila por tipo registrado). El
calculo del 所得税 que las consume es logica pura (`app.domain.tax`); aqui solo
se persiste y se traduce a `DeductionInput`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.fiscal_year_guard import require_open_fiscal_year
from app.db.session import get_db
from app.domain.tax.deduction_service import deductions_to_input, estimate_tax_saving
from app.domain.tax.income_source_service import (
    extra_income_inputs,
    jigyo_sales_revenue,
)
from app.domain.tax.income_tax import calculate
from app.domain.tax.schemas import IncomeInput, TaxCalculationInput
from app.models.entities import Deduction, FiscalYear, IncomeSource, Transaction
from app.models.enums import DeductionType
from app.services.tax_rules import TaxRules, load_tax_rules

logger = logging.getLogger(__name__)

router = APIRouter(tags=["deductions"])

# --- Ingresos del owner para situar el tramo marginal ---------------------
# El ahorro estimado y el summary necesitan los 所得 del owner para situar el
# tramo del 速算表. Antes el 売上 estaba HARDCODEADO (¥6,800,000); ahora se lee
# de `IncomeSource` (datos editables). El 青色特別控除 65万 se resta del 売上 para
# aproximar el 事業所得 (los 経費 de los 仕訳 se ignoran aca: es una estimacion
# del tramo marginal, no el calculo definitivo —ese vive en `drafting.py`—).
OWNER_AOIRO_DEDUCTION = 650_000


def _owner_incomes(db: Session, fiscal_year_id: uuid.UUID) -> list[dict[str, Any]]:
    """Ingresos del owner (leidos de `IncomeSource`) para situar el tramo marginal.

    Args:
        db: Sesion de BD.
        fiscal_year_id: Id del 年度.

    Returns:
        Lista de ingresos (`IncomeInput`-compatibles): un 事業所得 aproximado
        (売上 − 青色特別控除) + las fuentes complementarias (給与/雑/…). Si no hay
        ninguna `IncomeSource`, el 事業所得 es 0 (no el hardcode).
    """
    sources = list(
        db.scalars(
            select(IncomeSource).where(
                IncomeSource.fiscal_year_id == fiscal_year_id
            )
        ).all()
    )
    sales = jigyo_sales_revenue(sources)
    jigyo = max(0, sales - OWNER_AOIRO_DEDUCTION)
    incomes: list[dict[str, Any]] = [{"kind": "jigyo", "amount": jigyo}]
    incomes.extend(inc.model_dump() for inc in extra_income_inputs(sources))
    return incomes


# --- Schemas --------------------------------------------------------------


class DeductionCreate(BaseModel):
    """Cuerpo de creacion de una 控除.

    Args:
        type: Tipo de 所得控除 (enum `DeductionType`).
        amount: Monto declarado (yenes). Para 医療費控除 es el gasto del anio.
        meta: Metadatos opcionales (ej. ``reimbursement`` para 医療費, ``kind``
            y ``count`` para 扶養, etiqueta libre).
        evidence_ref: Referencia al 控除証明書 si la hubiera.
    """

    type: DeductionType
    amount: int = Field(ge=0)
    meta: dict[str, Any] | None = None
    evidence_ref: str | None = None


class DeductionPatch(BaseModel):
    """Cuerpo de edicion de una 控除 (solo campos provistos)."""

    amount: int | None = Field(default=None, ge=0)
    meta: dict[str, Any] | None = None
    evidence_ref: str | None = None


class DeductionOut(BaseModel):
    """Una 控除 persistida."""

    id: uuid.UUID
    type: DeductionType
    amount: int
    meta: dict[str, Any] | None = None
    evidence_ref: str | None = None


class DeductionListOut(BaseModel):
    """Respuesta de `GET /deductions`: filas + total aplicado.

    Args:
        year: Anio fiscal consultado.
        deductions: Filas registradas.
        applied_total: Σ所得控除 efectivamente aplicado (incl. 基礎控除 y tras
            pisos/topes) — cuadra con la tarjeta "控除適用済み" del dashboard.
    """

    year: int
    deductions: list[DeductionOut]
    applied_total: int


class DeductionSummaryOut(BaseModel):
    """Respuesta de `GET /deductions/summary`: efecto en el impuesto.

    Args:
        year: Anio fiscal.
        applied_total: Σ所得控除 aplicado (incl. 基礎控除).
        tax_with_deductions: 所得税 (+復興税) con las 控除 registradas.
        tax_without_deductions: 所得税 (+復興税) solo con 基礎控除 (sin las del
            usuario) — referencia para el 節税額.
        total_saving: Ahorro total estimado por las 控除 registradas.
    """

    year: int
    applied_total: int
    tax_with_deductions: int
    tax_without_deductions: int
    total_saving: int


class SuggestionOut(BaseModel):
    """Una sugerencia proactiva de 控除 que el usuario podria estar perdiendo.

    Args:
        type: Tipo de 控除 sugerido (lleva al paso del wizard).
        label: Titulo corto en japones.
        reason: Por que se sugiere (evidencia / recordatorio).
        estimated_saving: Ahorro estimado si aplica (yenes) o ``None`` si no es
            calculable sin que el usuario ingrese el monto.
        already_registered: ``True`` si ya hay una 控除 de ese tipo registrada.
    """

    type: DeductionType
    label: str
    reason: str
    estimated_saving: int | None = None
    already_registered: bool = False


# --- Helpers --------------------------------------------------------------


def _resolve_fiscal_year(db: Session, year: int) -> FiscalYear:
    """Devuelve el 年度 del anio pedido o lanza 404.

    Args:
        db: Sesion de BD.
        year: Anio fiscal.

    Returns:
        El `FiscalYear` correspondiente.

    Raises:
        HTTPException: 404 si no existe ningun 年度 para ese anio.
    """
    fy = db.scalars(select(FiscalYear).where(FiscalYear.year == year)).first()
    if fy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "no_fiscal_year",
                "message": f"{year}年度が見つかりませんでした。",
                "details": {"year": year},
            },
        )
    return fy


def _load_rules(year: int) -> TaxRules:
    """Carga los parametros fiscales del anio o lanza 400.

    Args:
        year: Anio fiscal.

    Returns:
        `TaxRules` del anio.

    Raises:
        HTTPException: 400 si no hay parametros para el anio.
    """
    try:
        return load_tax_rules(year)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unsupported_fiscal_year",
                "message": f"{year}年の税制パラメータがありません。",
                "details": {"year": year},
            },
        ) from exc


def _list_deductions(db: Session, fiscal_year_id: uuid.UUID) -> list[Deduction]:
    """Lista las 控除 de un 年度 (orden estable por tipo)."""
    return list(
        db.scalars(
            select(Deduction)
            .where(Deduction.fiscal_year_id == fiscal_year_id)
            .order_by(Deduction.type)
        ).all()
    )


def _applied_total(
    db: Session,
    fiscal_year_id: uuid.UUID,
    deductions: list[Deduction],
    rules: TaxRules,
    year: int,
) -> int:
    """Σ所得控除 efectivo (incl. 基礎控除, tras pisos/topes) para el owner.

    Args:
        db: Sesion de BD.
        fiscal_year_id: Id del 年度.
        deductions: Filas registradas.
        rules: Parametros fiscales.
        year: Anio fiscal.

    Returns:
        El `total_income_deductions` del calculo real.
    """
    result = calculate(
        TaxCalculationInput(
            year=year,
            incomes=cast(list[IncomeInput], _owner_incomes(db, fiscal_year_id)),
            deductions=deductions_to_input(deductions, year=year),
        ),
        rules,
    )
    return result.total_income_deductions


def _to_out(ded: Deduction) -> DeductionOut:
    """Serializa una `Deduction` a `DeductionOut`."""
    return DeductionOut(
        id=ded.id,
        type=ded.type,
        amount=ded.amount,
        meta=ded.meta,
        evidence_ref=ded.evidence_ref,
    )


# --- CRUD -----------------------------------------------------------------


@router.get("/deductions", response_model=DeductionListOut)
def list_deductions(
    year: int = Query(default=2025), db: Session = Depends(get_db)
) -> DeductionListOut:
    """Lista las 控除 registradas del anio + total aplicado.

    Args:
        year: Anio fiscal (令和7 = 2025).
        db: Sesion de BD.

    Returns:
        `DeductionListOut` con las filas y el Σ控除 efectivo.
    """
    fy = _resolve_fiscal_year(db, year)
    rules = _load_rules(year)
    deductions = _list_deductions(db, fy.id)
    return DeductionListOut(
        year=year,
        deductions=[_to_out(d) for d in deductions],
        applied_total=_applied_total(db, fy.id, deductions, rules, year),
    )


@router.post("/deductions", response_model=DeductionOut, status_code=status.HTTP_201_CREATED)
def create_deduction(
    payload: DeductionCreate,
    year: int = Query(default=2025),
    db: Session = Depends(get_db),
) -> DeductionOut:
    """Crea una 控除 en el 年度 indicado.

    Args:
        payload: Datos de la deduccion (type, amount, meta).
        year: Anio fiscal destino.
        db: Sesion de BD.

    Returns:
        La `Deduction` creada.
    """
    fy = _resolve_fiscal_year(db, year)
    require_open_fiscal_year(fy)
    if payload.type == DeductionType.DISABILITY_SELF:
        if payload.amount != 270_000:
            raise HTTPException(status_code=422, detail="一般障害者控除は27万円です。")
        existing = db.scalar(select(Deduction.id).where(
            Deduction.fiscal_year_id == fy.id,
            Deduction.type == DeductionType.DISABILITY_SELF,
        ))
        if existing is not None:
            raise HTTPException(status_code=409, detail="本人の障害者控除は登録済みです。")
    ded = Deduction(
        fiscal_year_id=fy.id,
        type=payload.type,
        amount=payload.amount,
        meta=payload.meta,
        evidence_ref=payload.evidence_ref,
    )
    db.add(ded)
    db.commit()
    db.refresh(ded)
    logger.info("控除 creada type=%s amount=%s year=%s", ded.type, ded.amount, year)
    return _to_out(ded)


def _get_deduction_or_404(db: Session, deduction_id: uuid.UUID) -> Deduction:
    """Devuelve la 控除 o lanza 404."""
    ded = db.get(Deduction, deduction_id)
    if ded is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "控除が見つかりませんでした。", "details": {}},
        )
    return ded


@router.patch("/deductions/{deduction_id}", response_model=DeductionOut)
def patch_deduction(
    deduction_id: uuid.UUID, patch: DeductionPatch, db: Session = Depends(get_db)
) -> DeductionOut:
    """Edita el monto / meta de una 控除.

    Args:
        deduction_id: Id de la 控除.
        patch: Campos a actualizar (solo los provistos).
        db: Sesion de BD.

    Returns:
        La `Deduction` actualizada.
    """
    ded = _get_deduction_or_404(db, deduction_id)
    require_open_fiscal_year(ded.fiscal_year)
    if (ded.type == DeductionType.DISABILITY_SELF and patch.amount is not None
            and patch.amount != 270_000):
        raise HTTPException(status_code=422, detail="一般障害者控除は27万円です。")
    data = patch.model_dump(exclude_unset=True)
    for field_name, value in data.items():
        setattr(ded, field_name, value)
    db.commit()
    db.refresh(ded)
    return _to_out(ded)


@router.delete("/deductions/{deduction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deduction(deduction_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    """Borra una 控除.

    Args:
        deduction_id: Id de la 控除.
        db: Sesion de BD.
    """
    ded = _get_deduction_or_404(db, deduction_id)
    require_open_fiscal_year(ded.fiscal_year)
    db.delete(ded)
    db.commit()


# --- Integracion con el calculo -------------------------------------------


@router.get("/deductions/summary", response_model=DeductionSummaryOut)
def deductions_summary(
    year: int = Query(default=2025), db: Session = Depends(get_db)
) -> DeductionSummaryOut:
    """Devuelve el efecto de las 控除 registradas sobre el impuesto.

    Calcula el 所得税 (+復興税) con las 控除 del usuario y, como referencia, solo
    con el 基礎控除, para exponer el 節税額 total.

    Args:
        year: Anio fiscal.
        db: Sesion de BD.

    Returns:
        `DeductionSummaryOut` con el total aplicado y el ahorro.
    """
    fy = _resolve_fiscal_year(db, year)
    rules = _load_rules(year)
    deductions = _list_deductions(db, fy.id)

    from app.domain.tax.schemas import DeductionInput  # local: evita ciclo de tipos

    owner_incomes = _owner_incomes(db, fy.id)
    result_with = calculate(
        TaxCalculationInput(
            year=year,
            incomes=cast(list[IncomeInput], owner_incomes),
            deductions=deductions_to_input(deductions, year=year),
        ),
        rules,
    )
    result_base = calculate(
        TaxCalculationInput(
            year=year, incomes=cast(list[IncomeInput], owner_incomes), deductions=DeductionInput()
        ),
        rules,
    )
    return DeductionSummaryOut(
        year=year,
        applied_total=result_with.total_income_deductions,
        tax_with_deductions=result_with.total_tax,
        tax_without_deductions=result_base.total_tax,
        total_saving=max(result_base.total_tax - result_with.total_tax, 0),
    )


# --- Deteccion proactiva --------------------------------------------------

# Palabras clave de 取引先 que sugieren un gasto medico (医療費控除).
_MEDICAL_VENDOR_KEYWORDS = (
    "薬局",
    "ドラッグ",
    "クリニック",
    "医院",
    "病院",
    "歯科",
    "薬品",
    "調剤",
    "メディカル",
    "pharmacy",
    "clinic",
)
# Palabras clave que sugieren una ふるさと納税 / 寄附.
_FURUSATO_VENDOR_KEYWORDS = ("ふるさと", "ふるさと納税", "寄附", "寄付", "ふるなび", "さとふる")


def _matches(text: str | None, keywords: tuple[str, ...]) -> bool:
    """``True`` si ``text`` contiene alguna keyword (case-insensitive)."""
    if not text:
        return False
    lowered = text.lower()
    return any(k.lower() in lowered for k in keywords)


@router.get("/deductions/suggestions", response_model=list[SuggestionOut])
def deductions_suggestions(
    year: int = Query(default=2025),
    db: Session = Depends(get_db),
) -> list[SuggestionOut]:
    """Analiza el 年度 y sugiere 控除 que el usuario podria estar perdiendo.

    Reglas:
        - 取引 de farmacia/clinica o 医療費 -> sugerir 医療費控除.
        - 取引 con vendor de ふるさと納税 -> recordar declararla (anula ワンストップ).
        - Recordatorios de los 控除 que casi todos tienen: 社会保険料, iDeCo,
          生命保険料 (solo si aun no estan registrados).

    El ahorro estimado se calcula con un monto tipico cuando es razonable, o se
    deja ``None`` si depende del importe que el usuario ingrese.

    Args:
        year: Anio fiscal.
        db: Sesion de BD.

    Returns:
        Lista de `SuggestionOut` ordenada por relevancia (evidencia primero).
    """
    fy = _resolve_fiscal_year(db, year)
    rules = _load_rules(year)
    existing = _list_deductions(db, fy.id)
    registered_types = {d.type for d in existing}

    transactions = list(
        db.scalars(
            select(Transaction).where(Transaction.fiscal_year_id == fy.id)
        ).all()
    )

    suggestions: list[SuggestionOut] = []

    def saving_for(ded_type: DeductionType, amount: int) -> int:
        """Ahorro estimado de agregar `amount` en `ded_type` al contexto actual."""
        probe = Deduction(fiscal_year_id=fy.id, type=ded_type, amount=amount)
        return estimate_tax_saving(
            probe, existing, _owner_incomes(db, fy.id), rules, year=year,
            filing_type=str(fy.filing_type_override or fy.taxpayer.filing_type),
        )

    # 1. Medico: por evidencia en transacciones (vendor de farmacia/clinica).
    medical_txs = [t for t in transactions if _matches(t.vendor, _MEDICAL_VENDOR_KEYWORDS)]
    if medical_txs and DeductionType.IRYOHI not in registered_types:
        total_medical = sum(t.total_amount for t in medical_txs)
        names = "・".join(dict.fromkeys(t.vendor for t in medical_txs if t.vendor))
        suggestions.append(
            SuggestionOut(
                type=DeductionType.IRYOHI,
                label="医療費控除の可能性",
                reason=(
                    f"医療機関・薬局での支払いが{len(medical_txs)}件見つかりました"
                    f"（{names}）。年間の医療費が10万円を超える場合、控除できます。"
                    "医療費控除の明細書が必要です。"
                ),
                estimated_saving=(
                    saving_for(DeductionType.IRYOHI, total_medical)
                    if total_medical > rules.deductions.iryohi_floor
                    else None
                ),
                already_registered=False,
            )
        )

    # 2. ふるさと納税: si hay evidencia, recordar declararla TODA (anula ワンストップ).
    furusato_txs = [t for t in transactions if _matches(t.vendor, _FURUSATO_VENDOR_KEYWORDS)]
    if furusato_txs and DeductionType.FURUSATO not in registered_types:
        total_furusato = sum(t.total_amount for t in furusato_txs)
        suggestions.append(
            SuggestionOut(
                type=DeductionType.FURUSATO,
                label="ふるさと納税の申告忘れに注意",
                reason=(
                    f"ふるさと納税らしき寄附が{len(furusato_txs)}件あります。"
                    "確定申告をする場合、ワンストップ特例は無効になります。"
                    "今年の寄附はすべて申告してください（寄附金控除）。"
                ),
                estimated_saving=saving_for(DeductionType.FURUSATO, total_furusato),
                already_registered=False,
            )
        )

    # 3. Recordatorios de los 控除 que casi todos tienen (si no estan registrados).
    common_reminders: list[tuple[DeductionType, str, str]] = [
        (
            DeductionType.SHAKAI_HOKEN,
            "社会保険料控除を忘れずに",
            "国民健康保険・国民年金などの支払いは全額が控除対象です。"
            "ほとんどの方が対象になります。控除証明書をご用意ください。",
        ),
        (
            DeductionType.IDECO,
            "iDeCo（小規模企業共済等）",
            "iDeCoや小規模企業共済の掛金は全額が控除対象です。"
            "加入している場合は払込証明書から金額を登録できます。",
        ),
        (
            DeductionType.SEIMEI_HOKEN,
            "生命保険料控除",
            "生命保険・介護医療保険・個人年金に加入していれば、"
            "最大12万円まで控除できます。控除証明書が秋〜冬に届きます。",
        ),
    ]
    for ded_type, label, reason in common_reminders:
        if ded_type in registered_types:
            continue
        suggestions.append(
            SuggestionOut(
                type=ded_type,
                label=label,
                reason=reason,
                estimated_saving=None,
                already_registered=False,
            )
        )

    logger.info("控除 suggestions year=%s -> %d", year, len(suggestions))
    return suggestions
