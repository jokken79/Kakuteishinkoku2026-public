"""Router del 消費税 (impuesto al consumo) — Fase 消費税.

Endpoints (bajo `/api/v1`):

- ``GET   /consumption/calculate?year=2025`` — calcula las 3 opciones
  (本則 / 簡易 / 2割特例), sin recomendar regímenes no verificados, y devuelve el desglose
  (売上税額 / 仕入税額控除 / 納付税額, separación 8% / 10%). Si el contribuyente es
  免税事業者 devuelve una respuesta clara con `is_taxable=false`.
- ``GET   /consumption/{year}/pdf``         — genera un informe de simulación
  (no es una declaración). 400 si es 免税事業者.
- ``GET   /taxpayer``                       — perfil del contribuyente (config
  del 消費税: 課税事業者 + metodo + 事業区分).
- ``PATCH /taxpayer``                       — actualiza la config del 消費税.

El informe no es un formulario oficial ni se envía a e-Tax.
"""

from __future__ import annotations

import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.tax.consumption import (
    BUSINESS_CATEGORY_LABELS,
    ConsumptionResult,
    calculate_consumption_for_year,
)
from app.models.entities import FiscalYear, Taxpayer
from app.models.enums import ConsumptionMethod
from app.services.forms.drafting import TaxpayerProfile, _era_birth_date, _mask_my_number
from app.services.forms.shohizei import render_shohizei
from app.services.tax_rules import load_tax_rules

logger = logging.getLogger(__name__)

router = APIRouter(tags=["consumption"])


# --- Schemas --------------------------------------------------------------


class TaxpayerConsumptionOut(BaseModel):
    """Config del 消費税 del contribuyente.

    Args:
        taxpayer_id: Id del 納税者.
        name: 氏名.
        is_taxable_consumption: ``True`` si es 課税事業者 (declara 消費税).
        consumption_method: Metodo elegido (honsoku / kani / tokurei_2wari).
        consumption_business_category: 事業区分 (1〜6) para 簡易課税, o ``None``.
        business_category_labels: Catalogo {区分: etiqueta} para la UI.
    """

    taxpayer_id: uuid.UUID
    name: str
    is_taxable_consumption: bool
    consumption_method: str | None
    consumption_business_category: int | None
    business_category_labels: dict[int, str]
    # 税務署 (提出先) — clave del 税務署 de presentación (None => default 津島).
    filing_office: str | None = None
    # Si el onboarding guiado fue completado (para el botón "rehacer" del 設定).
    onboarded: bool = True


class TaxpayerConsumptionPatch(BaseModel):
    """Cambios de la config del 消費税 (solo campos provistos).

    Args:
        is_taxable_consumption: Marca/desmarca como 課税事業者.
        consumption_method: Metodo (honsoku / kani / tokurei_2wari).
        consumption_business_category: 事業区分 (1〜6) del 簡易課税.
    """

    is_taxable_consumption: bool | None = None
    consumption_method: ConsumptionMethod | None = None
    consumption_business_category: int | None = Field(default=None, ge=1, le=6)
    # 税務署 (提出先) — clave del 税務署 (ej. "tsushima"); None deja el actual.
    filing_office: str | None = Field(default=None, max_length=64)
    # Permite rehacer el onboarding (setear False desde el 設定).
    onboarded: bool | None = None


# --- Helpers --------------------------------------------------------------


def _resolve_year_or_400(year: int) -> None:
    """Valida que existan parametros fiscales del anio (400 si no)."""
    try:
        load_tax_rules(year)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unsupported_fiscal_year",
                "message": f"{year}年の税制パラメータがありません。",
                "details": {"year": year},
            },
        ) from exc


def _get_taxpayer_or_404(db: Session) -> Taxpayer:
    """Devuelve el (único) 納税者 del MVP single-user o lanza 404."""
    taxpayer = db.scalars(select(Taxpayer)).first()
    if taxpayer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "no_taxpayer",
                "message": "納税者が登録されていません。",
                "details": {},
            },
        )
    return taxpayer


def _taxpayer_profile(db: Session, year: int) -> TaxpayerProfile | None:
    """Construye el `TaxpayerProfile` del 年度 para el encabezado del PDF."""
    fy = db.scalars(select(FiscalYear).where(FiscalYear.year == year)).first()
    taxpayer = fy.taxpayer if fy else _get_taxpayer_or_404(db)
    if taxpayer is None:
        return None
    return TaxpayerProfile(
        name=taxpayer.name,
        name_kana=taxpayer.name_kana,
        postal_code=taxpayer.postal_code,
        address=taxpayer.address,
        my_number_masked=_mask_my_number(taxpayer.my_number),
        birth_date_label=_era_birth_date(taxpayer.birth_date),
        occupation=taxpayer.business_type,
        filing_office_key=getattr(taxpayer, "filing_office", None),
    )


# --- Endpoints: calculo ---------------------------------------------------


@router.get("/consumption/calculate", response_model=ConsumptionResult)
def calculate_consumption(
    year: int = Query(default=2025), db: Session = Depends(get_db)
) -> ConsumptionResult:
    """Calcula el 消費税 del 年度: 3 opciones + sugerencia de menor pago.

    Args:
        year: 年度 (令和7 = 2025).
        db: Sesion de BD.

    Returns:
        `ConsumptionResult` con 本則 / 簡易 / 2割特例, el desglose 8%/10% y la
        recomendacion. Si el contribuyente es 免税事業者, `is_taxable` es
        ``False`` y `recommended` es ``None``.

    Raises:
        HTTPException: 400 si el anio no tiene parametros; 404 si no hay 年度.
    """
    _resolve_year_or_400(year)
    try:
        return calculate_consumption_for_year(db, year)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "no_fiscal_year",
                "message": f"{year}年度が見つかりませんでした。",
                "details": {"year": year},
            },
        ) from exc


@router.get("/consumption/{year}/pdf")
def get_consumption_pdf(
    year: int, db: Session = Depends(get_db)
) -> StreamingResponse:
    """Genera el informe PDF de simulación de 消費税 del 年度.

    Args:
        year: 年度 (令和7 = 2025).
        db: Sesion de BD.

    Returns:
        `StreamingResponse` con el PDF (application/pdf).

    Raises:
        HTTPException: 400 si el anio no tiene parametros o el contribuyente es
            免税事業者; 404 si no hay 年度.
    """
    _resolve_year_or_400(year)
    try:
        result = calculate_consumption_for_year(db, year)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "no_fiscal_year",
                "message": f"{year}年度が見つかりませんでした。",
                "details": {"year": year},
            },
        ) from exc

    if not result.is_taxable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "menzei_jigyosha",
                "message": "免税事業者のため、消費税の申告書は不要です。",
                "details": {"year": year},
            },
        )

    fy = db.scalars(select(FiscalYear).where(FiscalYear.year == year)).first()
    taxpayer_name = fy.taxpayer.name if fy and fy.taxpayer else "—"
    profile = _taxpayer_profile(db, year)
    content = render_shohizei(
        result, taxpayer_name=taxpayer_name, taxpayer_profile=profile
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="shohizei_{year}.pdf"'
        },
    )


# --- Endpoints: config del contribuyente ----------------------------------


def _to_taxpayer_out(taxpayer: Taxpayer) -> TaxpayerConsumptionOut:
    """Serializa la config del 消費税 de un `Taxpayer`."""
    raw_method = taxpayer.consumption_method
    method = getattr(raw_method, "value", raw_method)
    return TaxpayerConsumptionOut(
        taxpayer_id=taxpayer.id,
        name=taxpayer.name,
        is_taxable_consumption=bool(taxpayer.is_taxable_consumption),
        consumption_method=method,
        consumption_business_category=taxpayer.consumption_business_category,
        business_category_labels=BUSINESS_CATEGORY_LABELS,
        filing_office=getattr(taxpayer, "filing_office", None),
        onboarded=bool(getattr(taxpayer, "onboarded", True)),
    )


@router.get("/taxpayer", response_model=TaxpayerConsumptionOut)
def get_taxpayer(db: Session = Depends(get_db)) -> TaxpayerConsumptionOut:
    """Devuelve la config del 消費税 del contribuyente.

    Args:
        db: Sesion de BD.

    Returns:
        `TaxpayerConsumptionOut` con la config actual (課税事業者 + metodo + 区分).
    """
    return _to_taxpayer_out(_get_taxpayer_or_404(db))


@router.patch("/taxpayer", response_model=TaxpayerConsumptionOut)
def patch_taxpayer(
    patch: TaxpayerConsumptionPatch, db: Session = Depends(get_db)
) -> TaxpayerConsumptionOut:
    """Actualiza la config del 消費税 del contribuyente.

    Marcar `is_taxable_consumption=true` habilita la seccion 消費税 en la UI y el
    calculo/PDF. El metodo y el 事業区分 ajustan el calculo del 簡易課税.

    Args:
        patch: Campos a actualizar (solo los provistos).
        db: Sesion de BD.

    Returns:
        La config actualizada.
    """
    taxpayer = _get_taxpayer_or_404(db)
    data = patch.model_dump(exclude_unset=True)
    if "is_taxable_consumption" in data:
        taxpayer.is_taxable_consumption = bool(data["is_taxable_consumption"])
    if "consumption_method" in data:
        method = data["consumption_method"]
        taxpayer.consumption_method = (
            getattr(method, "value", method) if method is not None else None
        )
    if "consumption_business_category" in data:
        taxpayer.consumption_business_category = data["consumption_business_category"]
    if "filing_office" in data:
        taxpayer.filing_office = data["filing_office"]
    if "onboarded" in data and data["onboarded"] is not None:
        taxpayer.onboarded = bool(data["onboarded"])
    db.commit()
    db.refresh(taxpayer)
    logger.info(
        "Taxpayer config 消費税: 課税=%s 方法=%s 区分=%s",
        taxpayer.is_taxable_consumption,
        taxpayer.consumption_method,
        taxpayer.consumption_business_category,
    )
    return _to_taxpayer_out(taxpayer)
