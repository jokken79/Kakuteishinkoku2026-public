"""Router de importacion de CSV de banco/tarjeta (Fase 4-1).

Endpoints (bajo `/api/v1`):

- ``POST /import/csv/preview`` — sube CSV (+ mapping opcional) -> filas parseadas
  con su 仕訳 propuesto y flag de duplicado, SIN persistir.
- ``POST /import/csv/commit``  — persiste las filas seleccionadas como
  transacciones ``pending`` (entran a la bandeja de 仕訳).

Alcance: solo GASTOS (debitos). Los ingresos (入金) se descartan. Nada se
auto-confirma: toda transaccion nace ``pending`` para revision humana, igual
que el flujo de OCR.

Idempotencia: un re-import del mismo extracto no duplica. El duplicado se
detecta por (fecha + monto + vendor) contra las transacciones ya existentes del
年度 (mismo criterio que el seed de dev).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.fiscal_year_guard import require_open_fiscal_year
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.entities import FiscalYear, Transaction
from app.models.enums import TransactionSource, TransactionStatus
from app.services.fiscal_years import resolve_active_fiscal_year
from app.services.import_csv.builder import build_proposal
from app.services.import_csv.parser import (
    ColumnMapping,
    ParsedCsvRow,
    parse_csv,
    row_dedup_hash,
)

logger = logging.getLogger(__name__)

DateType = date

router = APIRouter(tags=["import-csv"])


# --- Schemas --------------------------------------------------------------


class ColumnMappingIn(BaseModel):
    """Mapeo manual de columnas (override de la auto-deteccion).

    Los valores son indices de columna (0-based). Se omiten los ausentes.
    """

    date: int | None = None
    vendor: int | None = None
    amount: int | None = None
    debit: int | None = None
    credit: int | None = None

    def to_domain(self) -> ColumnMapping:
        """Convierte a la `ColumnMapping` del servicio."""
        return ColumnMapping(
            date=self.date,
            vendor=self.vendor,
            amount=self.amount,
            debit=self.debit,
            credit=self.credit,
        )


class JournalLineOut(BaseModel):
    """Linea de 仕訳 propuesta."""

    side: str
    account_code: str
    amount: int
    tax_rate: int | None = None


class JournalSuggestionOut(BaseModel):
    """仕訳 candidato propuesto para una fila del CSV."""

    date: DateType | None
    description: str
    lines: list[JournalLineOut]
    account_code: str = Field(description="勘定科目 sugerido para el gasto")
    account_confidence: float


class PreviewRowOut(BaseModel):
    """Una fila del preview: datos parseados + 仕訳 propuesto + flags."""

    index: int = Field(description="Numero de fila en el CSV (1-based, sin header)")
    dedup_hash: str
    date: DateType | None
    vendor: str | None
    total_amount: int | None
    tax_lines: list[dict[str, Any]]
    account_code: str | None
    is_expense: bool
    is_duplicate: bool
    importable: bool
    skipped_reason: str | None = None
    journal_suggestion: JournalSuggestionOut | None = None


class ColumnMappingOut(BaseModel):
    """Mapeo de columnas detectado/usado (indices 0-based, ``None`` ausentes)."""

    date: int | None
    vendor: int | None
    amount: int | None
    debit: int | None
    credit: int | None


class PreviewResponse(BaseModel):
    """Respuesta de `POST /import/csv/preview`."""

    encoding: str
    headers: list[str]
    mapping: ColumnMappingOut
    mapping_ok: bool = Field(
        description="True si se detectaron fecha + monto (si no, re-mapear)"
    )
    total_rows: int
    importable_count: int
    duplicate_count: int
    rows: list[PreviewRowOut]


class CommitRowIn(BaseModel):
    """Una fila a persistir en el commit.

    El cliente envia los campos (posiblemente editados en el preview, ej. el
    勘定科目) para no depender de re-parsear el archivo.
    """

    dedup_hash: str
    date: DateType
    vendor: str | None = None
    total_amount: int
    account_code: str | None = None
    tax_lines: list[dict[str, Any]] = Field(default_factory=list)


class CommitRequest(BaseModel):
    """Pedido de commit: filas seleccionadas a importar."""

    rows: list[CommitRowIn]
    fiscal_year_id: uuid.UUID | None = None


class CommitResponse(BaseModel):
    """Respuesta de `POST /import/csv/commit`."""

    imported: int
    skipped_duplicates: int
    transaction_ids: list[uuid.UUID]


# --- Helpers --------------------------------------------------------------


def _resolve_fiscal_year(
    db: Session, fiscal_year_id: uuid.UUID | None
) -> FiscalYear | None:
    """Devuelve el 年度 pedido, o el ultimo abierto (MVP single-user)."""
    if fiscal_year_id is not None:
        return db.get(FiscalYear, fiscal_year_id)
    return resolve_active_fiscal_year(db)


def _existing_hashes(db: Session, fiscal_year_id: uuid.UUID) -> set[str]:
    """Calcula los hashes de dedup de las transacciones ya existentes del 年度.

    Reusa `row_dedup_hash` sobre (fecha, monto, vendor) de cada transaccion
    persistida, de modo que el criterio de duplicado sea identico al del parser.

    Args:
        db: Sesion de BD.
        fiscal_year_id: 年度 a inspeccionar.

    Returns:
        Conjunto de hashes existentes.
    """
    txs = db.scalars(
        select(Transaction).where(Transaction.fiscal_year_id == fiscal_year_id)
    ).all()
    return {row_dedup_hash(t.date, t.total_amount, t.vendor) for t in txs}


def _row_to_preview(
    row: ParsedCsvRow, *, is_duplicate: bool
) -> PreviewRowOut:
    """Serializa una fila parseada a `PreviewRowOut` con su 仕訳 propuesto."""
    journal: JournalSuggestionOut | None = None
    account_code: str | None = None
    tax_lines: list[dict[str, Any]] = []

    if row.is_importable:
        proposal = build_proposal(row)
        account_code = proposal.account_code
        tax_lines = proposal.tax_lines
        if proposal.journal is not None:
            journal = JournalSuggestionOut(
                date=proposal.journal.date,
                description=proposal.journal.description,
                lines=[
                    JournalLineOut(
                        side=ln.side,
                        account_code=ln.account_code,
                        amount=ln.amount,
                        tax_rate=ln.tax_rate,
                    )
                    for ln in proposal.journal.lines
                ],
                account_code=proposal.account_code,
                account_confidence=proposal.account_confidence,
            )

    return PreviewRowOut(
        index=row.index,
        dedup_hash=row.dedup_hash,
        date=row.date,
        vendor=row.vendor,
        total_amount=row.amount,
        tax_lines=tax_lines,
        account_code=account_code,
        is_expense=row.is_expense,
        is_duplicate=is_duplicate,
        importable=row.is_importable and not is_duplicate,
        skipped_reason=row.skipped_reason,
        journal_suggestion=journal,
    )


# --- Endpoints ------------------------------------------------------------


@router.post("/import/csv/preview", response_model=PreviewResponse)
async def preview_csv(
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None),
    fiscal_year_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PreviewResponse:
    """Parsea un CSV y devuelve las filas con su 仕訳 propuesto (sin persistir).

    Args:
        file: Archivo CSV (multipart). UTF-8 o SHIFT-JIS.
        mapping: JSON opcional con el mapeo manual de columnas (override).
        fiscal_year_id: 年度 destino (para detectar duplicados); usa el ultimo
            abierto si falta.
        db: Sesion de BD.
        settings: Settings.

    Returns:
        `PreviewResponse` con encoding, mapeo, conteos y filas (con flag de
        duplicado y 仕訳 propuesto por gasto).

    Raises:
        HTTPException: 400 si el archivo esta vacio o el mapping es invalido.
    """
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_file", "message": "CSVファイルが空です。", "details": {}},
        )

    manual_mapping: ColumnMapping | None = None
    if mapping:
        try:
            manual_mapping = ColumnMappingIn.model_validate_json(mapping).to_domain()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "invalid_mapping",
                    "message": "列のマッピングが不正です。",
                    "details": {"error": str(exc)},
                },
            ) from exc

    result = parse_csv(data, mapping=manual_mapping)

    fy_uuid = _parse_uuid(fiscal_year_id)
    fiscal_year = _resolve_fiscal_year(db, fy_uuid)
    existing = (
        _existing_hashes(db, fiscal_year.id) if fiscal_year is not None else set()
    )

    rows_out: list[PreviewRowOut] = []
    seen_in_file: set[str] = set()
    duplicate_count = 0
    importable_count = 0
    for row in result.rows:
        # Duplicado contra BD o contra una fila ya vista en el mismo archivo.
        is_dup = row.is_importable and (
            row.dedup_hash in existing or row.dedup_hash in seen_in_file
        )
        if row.is_importable:
            seen_in_file.add(row.dedup_hash)
        if is_dup:
            duplicate_count += 1
        preview = _row_to_preview(row, is_duplicate=is_dup)
        if preview.importable:
            importable_count += 1
        rows_out.append(preview)

    m = result.mapping
    return PreviewResponse(
        encoding=result.encoding,
        headers=result.headers,
        mapping=ColumnMappingOut(
            date=m.date, vendor=m.vendor, amount=m.amount, debit=m.debit, credit=m.credit
        ),
        mapping_ok=m.is_usable,
        total_rows=len(result.rows),
        importable_count=importable_count,
        duplicate_count=duplicate_count,
        rows=rows_out,
    )


@router.post("/import/csv/commit", response_model=CommitResponse)
def commit_csv(
    payload: CommitRequest, db: Session = Depends(get_db)
) -> CommitResponse:
    """Persiste las filas seleccionadas como transacciones ``pending``.

    Idempotente: si una fila ya existe en el 年度 (mismo hash de dedup) se omite.
    Las transacciones nacen ``pending`` (source=``csv``) y entran a la bandeja
    de 仕訳; nunca se auto-confirman.

    Args:
        payload: Filas a importar (+ 年度 opcional).
        db: Sesion de BD.

    Returns:
        `CommitResponse` con cuantas se importaron y cuantas se omitieron por
        duplicado.

    Raises:
        HTTPException: 422 si no hay 年度 abierto.
    """
    fiscal_year = _resolve_fiscal_year(db, payload.fiscal_year_id)
    if fiscal_year is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "no_fiscal_year",
                "message": "取引を登録する年度がありません。",
                "details": {},
            },
        )
    require_open_fiscal_year(fiscal_year)

    existing = _existing_hashes(db, fiscal_year.id)
    imported_ids: list[uuid.UUID] = []
    skipped = 0
    seen: set[str] = set()

    for item in payload.rows:
        h = item.dedup_hash or row_dedup_hash(
            item.date, item.total_amount, item.vendor
        )
        if h in existing or h in seen:
            skipped += 1
            continue
        seen.add(h)

        tx = Transaction(
            fiscal_year_id=fiscal_year.id,
            date=item.date,
            vendor=item.vendor,
            total_amount=item.total_amount,
            source=TransactionSource.CSV,
            confidence=None,
            status=TransactionStatus.PENDING,
            tax_lines=item.tax_lines or None,
            account_code=item.account_code,
        )
        db.add(tx)
        db.flush()
        imported_ids.append(tx.id)

    db.commit()
    logger.info(
        "Import CSV: %d transacciones nuevas, %d duplicados omitidos.",
        len(imported_ids),
        skipped,
    )
    return CommitResponse(
        imported=len(imported_ids),
        skipped_duplicates=skipped,
        transaction_ids=imported_ids,
    )


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    """Convierte un string a UUID, devolviendo ``None`` si es vacio/invalido."""
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
