"""Router del ONBOARDING guiado — configuración de primera vez.

Endpoints (bajo `/api/v1`):

- ``GET  /onboarding/status``    — estado del onboarding:
  ``{onboarded, has_taxpayer, has_income}``. El frontend lo consulta al cargar:
  si ``onboarded`` es ``False`` muestra el flujo guiado en vez del dashboard.
- ``POST /onboarding/complete``  — recibe el perfil completo (datos personales +
  申告区分 + 消費税 + 税務署 + ingresos iniciales), crea/actualiza el `Taxpayer`,
  asegura el `FiscalYear` del año y persiste las `IncomeSource` iniciales, y
  marca ``onboarded=True``. Reúsa la lógica de persistencia de taxpayer/income
  (mismas entidades; sin duplicar cálculo fiscal).

Diseño single-user (MVP): hay un único `Taxpayer`. Si ya existe se actualiza;
si no, se crea. ``POST /onboarding/complete`` es idempotente respecto al
`FiscalYear` y a las `IncomeSource` (una fila por `income_type`).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.fiscal_year_guard import require_open_fiscal_year
from app.db.session import get_db
from app.models.entities import FiscalYear, IncomeSource, Taxpayer
from app.models.enums import FilingType, IncomeType
from app.services.fiscal_years import ensure_fiscal_year

logger = logging.getLogger(__name__)

router = APIRouter(tags=["onboarding"])

# Año fiscal activo del MVP single-user (令和7 = 2025).
_DEFAULT_YEAR = 2025


# --- Schemas --------------------------------------------------------------


class OnboardingStatus(BaseModel):
    """Estado del onboarding del contribuyente.

    Args:
        onboarded: ``True`` si el usuario ya completó la configuración guiada.
        has_taxpayer: ``True`` si existe un `Taxpayer` registrado.
        has_income: ``True`` si hay alguna `IncomeSource` con monto/源泉 > 0.
    """

    onboarded: bool
    has_taxpayer: bool
    has_income: bool


class OnboardingIncome(BaseModel):
    """Un ingreso inicial declarado en el onboarding.

    Args:
        income_type: Tipo de 所得 (jigyo/kyuyo/zatsu/fudosan).
        gross: 収入金額 bruto (売上 para jigyo, 収入 para kyuyo).
        withholding: 源泉徴収税額 (del 源泉徴収票 / 支払調書).
        expenses: 必要経費 (zatsu/fudosan); para jigyo es informativo.
    """

    income_type: IncomeType
    gross: int = Field(default=0, ge=0)
    withholding: int = Field(default=0, ge=0)
    expenses: int = Field(default=0, ge=0)


class OnboardingComplete(BaseModel):
    """Perfil completo enviado al finalizar el onboarding.

    Todos los campos del perfil son opcionales (el usuario puede saltar pasos
    opcionales). Lo único que cambia siempre es ``onboarded -> True``.

    Args:
        name: 氏名 (nombre del contribuyente).
        name_kana: フリガナ (lectura katakana).
        my_number: 個人番号 (マイナンバー, opcional, sensible).
        postal_code: 郵便番号 del 納税地.
        address: 住所 del 納税地.
        birth_date: 生年月日.
        business_type: 職業 / 業種.
        filing_type: 申告区分 (aoiro_65 / aoiro_55 / aoiro_10 / shiroiro).
        is_taxable_consumption: ``True`` si es 課税事業者 (declara 消費税).
        filing_office: Clave del 税務署 de presentación (ej. "tsushima").
        incomes: Ingresos iniciales (売上 / 給与 + 源泉 / etc.).
    """

    name: str | None = Field(default=None, max_length=255)
    name_kana: str | None = Field(default=None, max_length=255)
    my_number: str | None = Field(default=None, max_length=512)
    postal_code: str | None = Field(default=None, max_length=16)
    address: str | None = Field(default=None, max_length=512)
    birth_date: date | None = None
    business_type: str | None = Field(default=None, max_length=128)
    filing_type: FilingType | None = None
    is_taxable_consumption: bool | None = None
    filing_office: str | None = Field(default=None, max_length=64)
    incomes: list[OnboardingIncome] = Field(default_factory=list)


class OnboardingCompleteOut(BaseModel):
    """Resultado del `POST /onboarding/complete`.

    Args:
        onboarded: Siempre ``True`` tras completar.
        taxpayer_id: Id del `Taxpayer` creado/actualizado.
        year: Año fiscal del `FiscalYear` asegurado.
        income_count: Nº de `IncomeSource` persistidas/actualizadas.
    """

    onboarded: bool
    taxpayer_id: uuid.UUID
    year: int
    income_count: int


# --- Helpers --------------------------------------------------------------


def _get_taxpayer(db: Session) -> Taxpayer | None:
    """Devuelve el (único) `Taxpayer` del MVP single-user, o ``None``."""
    return db.scalars(select(Taxpayer)).first()


def _upsert_income(db: Session, fy: FiscalYear, item: OnboardingIncome) -> None:
    """Crea o actualiza la `IncomeSource` del tipo dado (una fila por tipo).

    Reúsa el mismo patrón que el router de 収入 (gross/withholding + expenses en
    `meta`). Idempotente: si ya hay una fila de ese `income_type` la actualiza.

    Args:
        db: Sesión de BD.
        fy: 年度 destino.
        item: Ingreso a persistir.
    """
    existing = db.scalars(
        select(IncomeSource).where(
            IncomeSource.fiscal_year_id == fy.id,
            IncomeSource.income_type == item.income_type,
        )
    ).first()
    meta: dict[str, Any] | None = (
        {"expenses": item.expenses} if "expenses" in item.model_fields_set else None
    )
    if existing is not None:
        if "gross" in item.model_fields_set:
            existing.gross = item.gross
        if "withholding" in item.model_fields_set:
            existing.withholding = item.withholding
        if meta is not None:
            merged = dict(existing.meta or {})
            merged["expenses"] = item.expenses
            existing.meta = merged
        return
    db.add(
        IncomeSource(
            fiscal_year_id=fy.id,
            income_type=item.income_type,
            gross=item.gross,
            withholding=item.withholding,
            meta=meta,
        )
    )


# --- Endpoints ------------------------------------------------------------


@router.get("/onboarding/status", response_model=OnboardingStatus)
def get_onboarding_status(
    year: int = Query(default=_DEFAULT_YEAR), db: Session = Depends(get_db)
) -> OnboardingStatus:
    """Devuelve el estado del onboarding del contribuyente.

    Si no hay `Taxpayer` aún, ``onboarded`` es ``False`` (usuario nuevo).

    Args:
        year: Año fiscal a inspeccionar para `has_income`.
        db: Sesión de BD.

    Returns:
        `OnboardingStatus` con onboarded / has_taxpayer / has_income.
    """
    taxpayer = _get_taxpayer(db)
    if taxpayer is None:
        return OnboardingStatus(onboarded=False, has_taxpayer=False, has_income=False)

    fy = db.scalars(
        select(FiscalYear).where(
            FiscalYear.taxpayer_id == taxpayer.id, FiscalYear.year == year
        )
    ).first()
    has_income = False
    if fy is not None:
        has_income = any(
            (s.gross or 0) > 0 or (s.withholding or 0) > 0
            for s in db.scalars(
                select(IncomeSource).where(IncomeSource.fiscal_year_id == fy.id)
            ).all()
        )
    return OnboardingStatus(
        onboarded=bool(taxpayer.onboarded),
        has_taxpayer=True,
        has_income=has_income,
    )


@router.post(
    "/onboarding/complete",
    response_model=OnboardingCompleteOut,
    status_code=status.HTTP_200_OK,
)
def complete_onboarding(
    payload: OnboardingComplete,
    year: int = Query(default=_DEFAULT_YEAR),
    db: Session = Depends(get_db),
) -> OnboardingCompleteOut:
    """Completa el onboarding: crea/actualiza el perfil y marca onboarded.

    Reúsa las entidades existentes (`Taxpayer`, `FiscalYear`, `IncomeSource`):
    no duplica el cálculo fiscal (eso lo sigue haciendo `/filing/draft`).

    Args:
        payload: Perfil completo (datos personales + 申告区分 + 消費税 + 税務署 +
            ingresos iniciales).
        year: Año fiscal destino del 年度 e ingresos.
        db: Sesión de BD.

    Returns:
        `OnboardingCompleteOut` con el id del taxpayer, el año y el nº de
        ingresos persistidos.
    """
    taxpayer = _get_taxpayer(db)
    new_taxpayer = taxpayer is None
    if taxpayer is None:
        taxpayer = Taxpayer(name=payload.name or "—")
        db.add(taxpayer)
        db.flush()

    fy = ensure_fiscal_year(db, taxpayer, year)
    require_open_fiscal_year(fy)

    # Nunca escoger arbitrariamente una de varias fuentes del mismo tipo.
    requested_types: set[IncomeType] = set()
    for item in payload.incomes:
        if item.income_type in requested_types:
            raise HTTPException(status_code=409, detail={
                "code": "onboarding_income_ambiguous",
                "message": (
                    "Hay ingresos repetidos del mismo tipo. Revísalos en la pantalla de ingresos; "
                    "no se ha guardado la configuración."
                ),
            })
        requested_types.add(item.income_type)
        existing = db.scalars(select(IncomeSource.id).where(
            IncomeSource.fiscal_year_id == fy.id,
            IncomeSource.income_type == item.income_type,
        ).limit(2)).all()
        if len(existing) > 1:
            raise HTTPException(status_code=409, detail={
                "code": "onboarding_income_ambiguous",
                "message": (
                    "Ya existen varias fuentes de este tipo. No se guardó la configuración. "
                    "Para conservarlas, vuelve al paso de ingresos, deja vacíos los importes "
                    "de ese tipo y después revísalos en la pantalla de ingresos."
                ),
            })

    # Datos personales (solo los provistos; campos opcionales se respetan).
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        taxpayer.name = data["name"]
    for field_name in (
        "name_kana",
        "my_number",
        "postal_code",
        "address",
        "birth_date",
        "business_type",
        "filing_office",
    ):
        if field_name in data:
            setattr(taxpayer, field_name, data[field_name])
    if payload.filing_type is not None:
        # La elección del asistente corresponde al ejercicio, no a los demás.
        fy.filing_type_override = payload.filing_type
        if new_taxpayer:
            taxpayer.filing_type = payload.filing_type
    if payload.is_taxable_consumption is not None:
        taxpayer.is_taxable_consumption = bool(payload.is_taxable_consumption)

    taxpayer.onboarded = True

    for item in payload.incomes:
        _upsert_income(db, fy, item)

    db.commit()
    db.refresh(taxpayer)
    logger.info(
        "Onboarding completado taxpayer=%s 申告区分=%s 課税=%s 税務署=%s 収入=%d",
        taxpayer.id,
        taxpayer.filing_type,
        taxpayer.is_taxable_consumption,
        taxpayer.filing_office,
        len(payload.incomes),
    )
    return OnboardingCompleteOut(
        onboarded=True,
        taxpayer_id=taxpayer.id,
        year=year,
        income_count=len(payload.incomes),
    )
