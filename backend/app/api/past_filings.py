"""Router de 過去の申告 — archivo histórico de declaraciones anteriores.

"Dropbox inteligente" del 確定申告: el owner sube el PDF de su 申告書 de un año
anterior y la app lo archiva (PDF original en disco + hash + indices) e intenta
extraer los montos clave (所得/納付額/還付額/年度/税務署) por texto. Sirve para
consulta histórica y comparación año a año.

Endpoints (bajo `/api/v1`):

- ``POST   /past-filings``            — sube PDF + year -> archiva + extrae.
- ``GET    /past-filings``            — lista por año + serie para comparación.
- ``PATCH  /past-filings/{id}``       — corrige los montos extraídos.
- ``DELETE /past-filings/{id}``       — borra el registro (y el PDF si queda huérfano).
- ``GET    /past-filings/{id}/pdf``   — devuelve el PDF original archivado.

電子帳簿保存法: el PDF original se conserva indexado por al menos 7 años.
Idempotencia por hash: subir el mismo PDF dos veces no duplica el registro.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.entities import PastFiling, Taxpayer
from app.services.past_filings import extract_past_filing

logger = logging.getLogger(__name__)

router = APIRouter(tags=["past-filings"])


# --- Schemas ---------------------------------------------------------------


class PastFilingOut(BaseModel):
    """Una declaración histórica archivada (registro persistido)."""

    id: uuid.UUID
    year: int
    original_filename: str | None
    uploaded_at: _dt.datetime
    total_income: int | None
    tax_paid: int | None
    tax_refund: int | None
    tax_office: str | None
    extraction_source: str
    file_hash: str


class PastFilingPoint(BaseModel):
    """Un punto de la serie año a año (para el gráfico de comparación)."""

    year: int
    total_income: int | None
    tax_paid: int | None
    tax_refund: int | None
    # Impuesto neto del año: 納付 positivo, 還付 negativo (para el eje del gráfico).
    net_tax: int | None


class PastFilingList(BaseModel):
    """Respuesta de `GET /past-filings`: registros + serie de comparación."""

    filings: list[PastFilingOut]
    comparison: list[PastFilingPoint]


class PastFilingUpload(BaseModel):
    """Resultado de `POST /past-filings`: el registro + si fue un duplicado."""

    filing: PastFilingOut
    # `True` si el PDF ya estaba archivado (mismo hash): no se duplicó.
    duplicate: bool
    # `True` si se extrajo al menos un monto del PDF (guía la UI: "revisá" vs
    # "completá a mano").
    extracted: bool


class PastFilingPatch(BaseModel):
    """Campos editables de un registro histórico (corrección manual)."""

    year: int | None = Field(default=None, ge=1989, le=2100)
    total_income: int | None = None
    tax_paid: int | None = None
    tax_refund: int | None = None
    tax_office: str | None = None


# --- Helpers ---------------------------------------------------------------


def _resolve_taxpayer(db: Session) -> Taxpayer | None:
    """Devuelve el (único) contribuyente del MVP single-user, o ``None``."""
    return db.scalars(select(Taxpayer).order_by(Taxpayer.created_at)).first()


def _net_tax(filing: PastFiling) -> int | None:
    """Impuesto neto del año: 納付 positivo, 還付 negativo, o ``None``.

    Args:
        filing: Registro histórico.

    Returns:
        Entero de yenes (positivo si pagó, negativo si le devolvieron), o
        ``None`` si no hay ni 納付額 ni 還付額.
    """
    if filing.tax_paid:
        return filing.tax_paid
    if filing.tax_refund:
        return -filing.tax_refund
    return None


def _to_out(filing: PastFiling) -> PastFilingOut:
    """Serializa un `PastFiling` a `PastFilingOut`."""
    return PastFilingOut(
        id=filing.id,
        year=filing.year,
        original_filename=filing.original_filename,
        uploaded_at=filing.uploaded_at,
        total_income=filing.total_income,
        tax_paid=filing.tax_paid,
        tax_refund=filing.tax_refund,
        tax_office=filing.tax_office,
        extraction_source=filing.extraction_source,
        file_hash=filing.file_hash,
    )


def _get_or_404(db: Session, filing_id: uuid.UUID) -> PastFiling:
    """Devuelve el registro o lanza 404."""
    filing = db.get(PastFiling, filing_id)
    if filing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": "過去の申告が見つかりませんでした。",
                "details": {},
            },
        )
    return filing


# --- Endpoints -------------------------------------------------------------


@router.post(
    "/past-filings",
    response_model=PastFilingUpload,
    status_code=status.HTTP_201_CREATED,
)
async def upload_past_filing(
    file: UploadFile = File(...),
    year: int | None = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PastFilingUpload:
    """Sube un PDF de 確定申告 viejo, lo archiva e intenta extraer los montos.

    Args:
        file: PDF del 申告書 de un año anterior (multipart).
        year: 年度 gregoriano (opcional; si falta, se usa el detectado del PDF).
        db: Sesión de BD.
        settings: Settings (carpeta de archivo).

    Returns:
        `PastFilingUpload` con el registro, si fue duplicado y si se extrajo algo.

    Raises:
        HTTPException: 400 si el archivo está vacío o no es PDF; 422 si no se
            pudo determinar el año (ni form ni PDF) o no hay contribuyente.
    """
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_file", "message": "ファイルが空です。", "details": {}},
        )

    # Validar que sea un PDF (cabecera %PDF). Evita archivar basura.
    if not pdf_bytes.lstrip()[:5].startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "not_pdf",
                "message": "PDFファイルをアップロードしてください。",
                "details": {},
            },
        )

    taxpayer = _resolve_taxpayer(db)
    if taxpayer is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "no_taxpayer",
                "message": "納税者が登録されていません。",
                "details": {},
            },
        )

    extracted = extract_past_filing(pdf_bytes)

    # Determinar el año: el form tiene prioridad; si falta, el detectado del PDF.
    resolved_year = year or extracted.year
    if resolved_year is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "year_required",
                "message": "年度を選択してください（PDFから自動検出できませんでした）。",
                "details": {},
            },
        )

    digest = hashlib.sha256(pdf_bytes).hexdigest()

    # Idempotencia por hash: si ya está archivado, devolver el existente.
    existing = db.scalars(
        select(PastFiling).where(PastFiling.file_hash == digest)
    ).first()
    if existing is not None:
        return PastFilingUpload(
            filing=_to_out(existing),
            duplicate=True,
            extracted=existing.extraction_source == "auto",
        )

    # Archivar el PDF original en disco (privado, 電子帳簿保存法).
    storage_dir = Path(settings.past_filings_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    target = storage_dir / f"{digest}.pdf"
    if not target.exists():
        target.write_bytes(pdf_bytes)

    filing = PastFiling(
        taxpayer_id=taxpayer.id,
        year=resolved_year,
        file_ref=str(target),
        file_hash=digest,
        uploaded_at=_dt.datetime.now(_dt.UTC),
        original_filename=file.filename,
        total_income=extracted.total_income,
        tax_paid=extracted.tax_paid,
        tax_refund=extracted.tax_refund,
        tax_office=extracted.tax_office,
        raw_text=extracted.raw_text or None,
        extraction_source="auto",
    )
    db.add(filing)
    db.commit()
    db.refresh(filing)

    return PastFilingUpload(
        filing=_to_out(filing),
        duplicate=False,
        extracted=extracted.any_amount_extracted,
    )


@router.get("/past-filings", response_model=PastFilingList)
def list_past_filings(db: Session = Depends(get_db)) -> PastFilingList:
    """Lista las declaraciones históricas ordenadas por año + serie comparativa.

    Args:
        db: Sesión de BD.

    Returns:
        `PastFilingList` con los registros (año desc) y la serie año a año (asc)
        para el gráfico de evolución del 所得 y del impuesto.
    """
    filings = list(
        db.scalars(select(PastFiling).order_by(PastFiling.year.desc())).all()
    )
    comparison = [
        PastFilingPoint(
            year=f.year,
            total_income=f.total_income,
            tax_paid=f.tax_paid,
            tax_refund=f.tax_refund,
            net_tax=_net_tax(f),
        )
        for f in sorted(filings, key=lambda f: f.year)
    ]
    return PastFilingList(
        filings=[_to_out(f) for f in filings],
        comparison=comparison,
    )


@router.patch("/past-filings/{filing_id}", response_model=PastFilingOut)
def patch_past_filing(
    filing_id: uuid.UUID,
    patch: PastFilingPatch,
    db: Session = Depends(get_db),
) -> PastFilingOut:
    """Corrige los montos extraídos de un registro histórico.

    Marca el registro como ``extraction_source='manual'`` (el usuario revisó).

    Args:
        filing_id: Id del registro.
        patch: Campos a actualizar (solo los provistos).
        db: Sesión de BD.

    Returns:
        `PastFilingOut` actualizada.
    """
    filing = _get_or_404(db, filing_id)
    data = patch.model_dump(exclude_unset=True)
    for field_name, value in data.items():
        setattr(filing, field_name, value)
    if data:
        filing.extraction_source = "manual"
    db.commit()
    db.refresh(filing)
    return _to_out(filing)


@router.delete("/past-filings/{filing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_past_filing(
    filing_id: uuid.UUID, db: Session = Depends(get_db)
) -> None:
    """Borra un registro histórico (y el PDF en disco si queda huérfano).

    Args:
        filing_id: Id del registro.
        db: Sesión de BD.
    """
    filing = _get_or_404(db, filing_id)
    file_ref = filing.file_ref
    file_hash = filing.file_hash
    db.delete(filing)
    db.commit()

    # Borrar el PDF solo si ningún otro registro lo referencia (mismo hash).
    still_used = db.scalars(
        select(PastFiling).where(PastFiling.file_hash == file_hash)
    ).first()
    if still_used is None:
        try:
            Path(file_ref).unlink(missing_ok=True)
        except OSError as exc:  # noqa: BLE001 — borrar el archivo es best-effort.
            logger.warning("No se pudo borrar el PDF histórico %s: %s", file_ref, exc)


@router.get("/past-filings/{filing_id}/pdf")
def get_past_filing_pdf(
    filing_id: uuid.UUID, db: Session = Depends(get_db)
) -> FileResponse:
    """Devuelve el PDF original archivado de un registro histórico.

    Args:
        filing_id: Id del registro.
        db: Sesión de BD.

    Returns:
        `FileResponse` con el PDF (Content-Type application/pdf).

    Raises:
        HTTPException: 404 si el registro o el archivo en disco no existen.
    """
    filing = _get_or_404(db, filing_id)
    path = Path(filing.file_ref)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "file_missing",
                "message": "アーカイブされたPDFが見つかりません。",
                "details": {},
            },
        )
    download_name = filing.original_filename or f"kakutei_{filing.year}.pdf"
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=download_name,
    )
