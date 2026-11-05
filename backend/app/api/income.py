"""Router del modulo de 収入 (IncomeSource) — ingresos editables del owner.

Endpoints (bajo `/api/v1`):

- ``GET    /income-sources?year=2025``  — lista las fuentes de ingreso del 年度.
- ``POST   /income-sources``            — crea una fuente (income_type, gross,
  withholding, expenses opcional, meta).
- ``PATCH  /income-sources/{id}``       — edita gross / withholding / meta.
- ``DELETE /income-sources/{id}``       — borra una fuente.

Esto SACA EL HARDCODE de 売上 ¥6,800,000 y 源泉徴収 ¥410,000: el owner ingresa SUS
ingresos reales y la declaracion sale con sus datos. El draft (`drafting.py`) lee
estas filas para armar el PL (売上) y el 源泉徴収 total.

Tipos soportados en el MVP:
    - **jigyo** (事業: 売上 — el ingreso principal del 個人事業主; los 経費 vienen
      de los 仕訳, por eso `expenses` aca es informativo/opcional).
    - **kyuyo** (給与: 収入金額 + 源泉徴収税額 del 源泉徴収票).
    - **zatsu** (雑所得: 収入 − 経費).
    - **fudosan** (不動産所得, opcional).
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
from app.models.entities import FiscalYear, IncomeSource
from app.models.enums import IncomeType

logger = logging.getLogger(__name__)

router = APIRouter(tags=["income"])

# Tipos de 所得 que el owner puede ingresar en el MVP (resto fuera de scope UI).
_SUPPORTED_TYPES: frozenset[IncomeType] = frozenset(
    {
        IncomeType.JIGYO,
        IncomeType.KYUYO,
        IncomeType.ZATSU,
        IncomeType.FUDOSAN,
    }
)


# --- Schemas --------------------------------------------------------------


class IncomeSourceCreate(BaseModel):
    """Cuerpo de creacion de una fuente de ingreso.

    Args:
        income_type: Tipo de 所得 (jigyo/kyuyo/zatsu/fudosan).
        gross: 収入金額 bruto (売上 para jigyo, 収入 para kyuyo, etc.).
        withholding: 源泉徴収税額 (del 源泉徴収票 / 支払調書). Default 0.
        expenses: 必要経費 (para zatsu/fudosan). Para jigyo es informativo (los
            経費 reales vienen de los 仕訳). Se guarda en `meta.expenses`.
        meta: Metadatos libres (etiqueta del 支払者, etc.).
    """

    income_type: IncomeType
    gross: int = Field(ge=0)
    withholding: int = Field(default=0, ge=0)
    expenses: int = Field(default=0, ge=0)
    meta: dict[str, Any] | None = None


class IncomeSourcePatch(BaseModel):
    """Cuerpo de edicion de una fuente (solo campos provistos)."""

    gross: int | None = Field(default=None, ge=0)
    withholding: int | None = Field(default=None, ge=0)
    expenses: int | None = Field(default=None, ge=0)
    meta: dict[str, Any] | None = None


class IncomeSourceOut(BaseModel):
    """Una fuente de ingreso persistida."""

    id: uuid.UUID
    income_type: IncomeType
    gross: int
    withholding: int
    expenses: int
    meta: dict[str, Any] | None = None


class IncomeSourceListOut(BaseModel):
    """Respuesta de `GET /income-sources`: filas + totales del 年度.

    Args:
        year: Anio fiscal consultado.
        income_sources: Filas registradas.
        sales_revenue: 売上 del 事業 (Σ filas jigyo) — el que entra al PL.
        total_withholding: Σ源泉徴収税額 de todas las fuentes — el que descuenta
            el 納付額.
    """

    year: int
    income_sources: list[IncomeSourceOut]
    sales_revenue: int
    total_withholding: int


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


def _ensure_supported(income_type: IncomeType) -> None:
    """Valida que el tipo este soportado en el MVP (400 si no).

    Args:
        income_type: Tipo de 所得 pedido.

    Raises:
        HTTPException: 400 si el tipo no esta soportado.
    """
    if income_type not in _SUPPORTED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unsupported_income_type",
                "message": f"未対応の所得区分です: {income_type.value}",
                "details": {"supported": sorted(t.value for t in _SUPPORTED_TYPES)},
            },
        )


def _list_sources(db: Session, fiscal_year_id: uuid.UUID) -> list[IncomeSource]:
    """Lista las fuentes de un 年度 (orden estable por tipo)."""
    return list(
        db.scalars(
            select(IncomeSource)
            .where(IncomeSource.fiscal_year_id == fiscal_year_id)
            .order_by(IncomeSource.income_type)
        ).all()
    )


def _to_out(source: IncomeSource) -> IncomeSourceOut:
    """Serializa una `IncomeSource` a `IncomeSourceOut`."""
    meta = source.meta or {}
    return IncomeSourceOut(
        id=source.id,
        income_type=source.income_type,
        gross=source.gross,
        withholding=source.withholding,
        expenses=int(cast(int, meta.get("expenses", 0))),
        meta=source.meta,
    )


def _merge_expenses(meta: dict[str, Any] | None, expenses: int | None) -> dict[str, Any] | None:
    """Guarda `expenses` dentro del `meta` (la entidad no tiene columna propia).

    Args:
        meta: Metadatos actuales (o nuevos).
        expenses: 必要経費 a guardar; ``None`` deja el meta tal cual.

    Returns:
        El `meta` resultante (puede ser ``None`` si no hay nada que guardar).
    """
    if expenses is None:
        return meta
    merged = dict(meta or {})
    merged["expenses"] = expenses
    return merged


# --- CRUD -----------------------------------------------------------------


@router.get("/income-sources", response_model=IncomeSourceListOut)
def list_income_sources(
    year: int = Query(default=2025), db: Session = Depends(get_db)
) -> IncomeSourceListOut:
    """Lista las fuentes de ingreso del 年度 + totales (売上 / 源泉).

    Args:
        year: Anio fiscal (令和7 = 2025).
        db: Sesion de BD.

    Returns:
        `IncomeSourceListOut` con las filas, el 売上 del 事業 y el 源泉徴収 total.
    """
    fy = _resolve_fiscal_year(db, year)
    sources = _list_sources(db, fy.id)
    sales = sum(s.gross for s in sources if s.income_type == IncomeType.JIGYO)
    withholding = sum(s.withholding for s in sources)
    return IncomeSourceListOut(
        year=year,
        income_sources=[_to_out(s) for s in sources],
        sales_revenue=sales,
        total_withholding=withholding,
    )


@router.post(
    "/income-sources",
    response_model=IncomeSourceOut,
    status_code=status.HTTP_201_CREATED,
)
def create_income_source(
    payload: IncomeSourceCreate,
    year: int = Query(default=2025),
    db: Session = Depends(get_db),
) -> IncomeSourceOut:
    """Crea una fuente de ingreso en el 年度 indicado.

    Args:
        payload: Datos de la fuente (income_type, gross, withholding, expenses).
        year: Anio fiscal destino.
        db: Sesion de BD.

    Returns:
        La `IncomeSource` creada.
    """
    _ensure_supported(payload.income_type)
    fy = _resolve_fiscal_year(db, year)
    require_open_fiscal_year(fy)
    source = IncomeSource(
        fiscal_year_id=fy.id,
        income_type=payload.income_type,
        gross=payload.gross,
        withholding=payload.withholding,
        meta=_merge_expenses(payload.meta, payload.expenses),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    logger.info(
        "IncomeSource creada type=%s gross=%s withholding=%s year=%s",
        source.income_type,
        source.gross,
        source.withholding,
        year,
    )
    return _to_out(source)


def _get_source_or_404(db: Session, source_id: uuid.UUID) -> IncomeSource:
    """Devuelve la fuente o lanza 404."""
    source = db.get(IncomeSource, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": "収入が見つかりませんでした。",
                "details": {},
            },
        )
    return source


@router.patch("/income-sources/{source_id}", response_model=IncomeSourceOut)
def patch_income_source(
    source_id: uuid.UUID, patch: IncomeSourcePatch, db: Session = Depends(get_db)
) -> IncomeSourceOut:
    """Edita gross / withholding / expenses / meta de una fuente.

    Editar el 売上 (gross de la fila jigyo) cambia el 事業所得 y el 納付額; editar
    el withholding cambia el 納付額.

    Args:
        source_id: Id de la fuente.
        patch: Campos a actualizar (solo los provistos).
        db: Sesion de BD.

    Returns:
        La `IncomeSource` actualizada.
    """
    source = _get_source_or_404(db, source_id)
    require_open_fiscal_year(source.fiscal_year)
    data = patch.model_dump(exclude_unset=True)
    expenses = data.pop("expenses", None)
    meta_patch = data.pop("meta", None)
    if meta_patch is not None:
        source.meta = {**(source.meta or {}), **meta_patch}
    if expenses is not None:
        source.meta = _merge_expenses(source.meta, expenses)
    for field_name, value in data.items():
        setattr(source, field_name, value)
    db.commit()
    db.refresh(source)
    return _to_out(source)


@router.delete(
    "/income-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_income_source(
    source_id: uuid.UUID, db: Session = Depends(get_db)
) -> None:
    """Borra una fuente de ingreso.

    Args:
        source_id: Id de la fuente.
        db: Sesion de BD.
    """
    source = _get_source_or_404(db, source_id)
    require_open_fiscal_year(source.fiscal_year)
    db.delete(source)
    db.commit()
