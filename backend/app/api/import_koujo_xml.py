"""Router de importacion de XML de 控除証明書 electrónicos (Nivel 2 e-Tax).

Endpoints (bajo `/api/v1`):

- ``POST /deductions/import-xml/preview`` — sube el .xml del 控除証明書 -> detecta
  el tipo (生命保険/地震/iDeCo/国民年金/寄附金), calcula el 控除額 y devuelve el
  preview SIN persistir.
- ``POST /deductions/import-xml/commit``  — crea (o actualiza) la `Deduction`
  correspondiente con el monto confirmado por el usuario.

Sigue el mismo patrón que el import de CSV (preview editable -> commit). El XML
se parsea con `koujo_parser` usando los XPaths del `koujo_schema.json` (XSD
oficiales del NTA). Nada se inventa: si un campo falta, el preview lo marca como
"requiere confirmación".

Para el 生命保険料控除 el 控除額 sale de la fórmula escalonada oficial; el usuario
siempre revisa el monto antes de confirmar (igual que el resto del wizard).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.fiscal_year_guard import require_open_fiscal_year
from app.db.session import get_db
from app.models.entities import Deduction, FiscalYear
from app.models.enums import DeductionType
from app.services.import_xml.koujo_parser import KoujoParseError, parse_koujo_xml

logger = logging.getLogger(__name__)

router = APIRouter(tags=["import-koujo-xml"])


# --- Schemas --------------------------------------------------------------


class KoujoSeimeiCategoryOut(BaseModel):
    """Desglose de una categoría del 生命保険料控除 (para mostrar en el preview)."""

    category: str
    label: str
    old_paid: int | None = None
    new_paid: int | None = None
    deduction: int


class KoujoPreviewResponse(BaseModel):
    """Respuesta de `POST /deductions/import-xml/preview`.

    Args:
        koujo_type: Etiqueta japonesa del tipo de 控除 detectado.
        root_element: Elemento raíz del XML (ej. ``TEG850``).
        deduction_type: `DeductionType` destino de la Deduction.
        amount: 控除額 propuesto (yenes). El usuario lo confirma/edita.
        issuer: Emisor / 保険会社名 / 団体名 / 被保険者名.
        year: Año 西暦 del certificado, o ``None``.
        needs_confirmation: ``True`` si el monto no es 100% determinable.
        note: Aviso japonés (cómo se calculó / qué confirmar).
        already_registered: ``True`` si ya hay una 控除 de ese tipo (se actualiza).
        seimei_categories: Desglose por categoría (solo 生命保険).
    """

    koujo_type: str
    root_element: str
    deduction_type: DeductionType
    amount: int
    issuer: str | None = None
    year: int | None = None
    needs_confirmation: bool = False
    note: str | None = None
    already_registered: bool = False
    seimei_categories: list[KoujoSeimeiCategoryOut] = Field(default_factory=list)


class KoujoCommitRequest(BaseModel):
    """Pedido de commit: crea/actualiza la 控除 con el monto confirmado.

    Args:
        deduction_type: Tipo de 控除 (del preview).
        amount: Monto a registrar (posiblemente editado por el usuario).
        issuer: Emisor para guardar en meta / evidence_ref.
        year: Año del certificado (informativo, va a meta).
        koujo_type: Etiqueta japonesa (va a meta para mostrar el origen).
    """

    deduction_type: DeductionType
    amount: int = Field(ge=0)
    issuer: str | None = None
    year: int | None = None
    koujo_type: str | None = None


class KoujoCommitResponse(BaseModel):
    """Respuesta de `POST /deductions/import-xml/commit`."""

    id: uuid.UUID
    type: DeductionType
    amount: int
    created: bool = Field(description="True si se creó; False si se actualizó una existente")


# --- Helpers --------------------------------------------------------------


def _resolve_fiscal_year(db: Session, year: int) -> FiscalYear:
    """Devuelve el 年度 del anio pedido o lanza 404."""
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


# --- Endpoints ------------------------------------------------------------


@router.post("/deductions/import-xml/preview", response_model=KoujoPreviewResponse)
async def preview_koujo_xml(
    file: UploadFile = File(...),
    year: int = 2025,
    db: Session = Depends(get_db),
) -> KoujoPreviewResponse:
    """Parsea un XML de 控除証明書 y devuelve el preview (sin persistir).

    Args:
        file: Archivo XML del 控除証明書 (multipart).
        year: Año fiscal destino (para saber si ya hay una 控除 del tipo).
        db: Sesion de BD.

    Returns:
        `KoujoPreviewResponse` con el tipo detectado, el 控除額 propuesto y el
        desglose.

    Raises:
        HTTPException: 400 si el XML está vacío, malformado o de un tipo no
            soportado (mensaje de dominio, nunca 500 crudo).
    """
    data = await file.read()
    try:
        result = parse_koujo_xml(data)
    except KoujoParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message, "details": exc.details},
        ) from exc

    # ¿Ya hay una 控除 del mismo tipo registrada en el 年度? (el commit la actualiza).
    already = False
    fy = db.scalars(select(FiscalYear).where(FiscalYear.year == year)).first()
    if fy is not None:
        existing = db.scalars(
            select(Deduction).where(
                Deduction.fiscal_year_id == fy.id,
                Deduction.type == result.deduction_type,
            )
        ).first()
        already = existing is not None

    seimei = [
        KoujoSeimeiCategoryOut(**c) for c in result.details.get("categories", [])
    ]

    return KoujoPreviewResponse(
        koujo_type=result.koujo_type,
        root_element=result.root_element,
        deduction_type=result.deduction_type,
        amount=result.amount,
        issuer=result.issuer,
        year=result.year,
        needs_confirmation=result.needs_confirmation,
        note=result.note,
        already_registered=already,
        seimei_categories=seimei,
    )


@router.post("/deductions/import-xml/commit", response_model=KoujoCommitResponse)
def commit_koujo_xml(
    payload: KoujoCommitRequest,
    year: int = 2025,
    db: Session = Depends(get_db),
) -> KoujoCommitResponse:
    """Crea o actualiza la `Deduction` del 控除証明書 importado.

    Si ya existe una 控除 del mismo tipo en el 年度, suma el monto (varios
    certificados del mismo tipo se acumulan, como pasa con 生命保険 de distintas
    aseguradoras o 寄附金 de varios municipios). Si no, la crea.

    Args:
        payload: Tipo + monto confirmado + metadatos del certificado.
        year: Año fiscal destino.
        db: Sesion de BD.

    Returns:
        `KoujoCommitResponse` con la 控除 resultante.

    Raises:
        HTTPException: 404 si no hay 年度 para el año.
    """
    fy = _resolve_fiscal_year(db, year)
    require_open_fiscal_year(fy)

    meta: dict[str, object] = {"source": "koujo_xml"}
    if payload.koujo_type:
        meta["koujo_type"] = payload.koujo_type
    if payload.issuer:
        meta["issuer"] = payload.issuer
    if payload.year is not None:
        meta["certificate_year"] = payload.year

    existing = db.scalars(
        select(Deduction).where(
            Deduction.fiscal_year_id == fy.id,
            Deduction.type == payload.deduction_type,
        )
    ).first()

    if existing is not None:
        # Acumula: un 2do certificado del mismo tipo se SUMA al registrado.
        existing.amount = existing.amount + payload.amount
        merged = dict(existing.meta or {})
        merged.update(meta)
        existing.meta = merged
        db.commit()
        db.refresh(existing)
        logger.info(
            "控除 XML actualizada type=%s amount=%s year=%s",
            existing.type,
            existing.amount,
            year,
        )
        return KoujoCommitResponse(
            id=existing.id, type=existing.type, amount=existing.amount, created=False
        )

    ded = Deduction(
        fiscal_year_id=fy.id,
        type=payload.deduction_type,
        amount=payload.amount,
        evidence_ref=payload.issuer,
        meta=meta,
    )
    db.add(ded)
    db.commit()
    db.refresh(ded)
    logger.info(
        "控除 XML creada type=%s amount=%s year=%s", ded.type, ded.amount, year
    )
    return KoujoCommitResponse(
        id=ded.id, type=ded.type, amount=ded.amount, created=True
    )
