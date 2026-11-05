"""Router de recibos y OCR (Fase 2, M1).

Endpoints (bajo `/api/v1`):

- ``POST /receipts``                 — sube imagen/PDF -> OCR -> 仕訳 propuesto.
- ``GET  /receipts?status=pending``  — bandeja de revision.
- ``POST /receipts/{id}/confirm``    — confirma la transaccion propuesta.
- ``PATCH /receipts/{id}``           — edita campos extraidos / 勘定科目.
- ``POST /receipts/batch-confirm``   — confirma N transacciones.
- ``GET  /ocr/providers``            — estado de los proveedores (toggle on/off).

La imagen se archiva como `Evidence` (hash, timestamp, indices 日付/金額/取引先 —
電帳法). El cuadre/registro fallido nunca auto-confirma: la transaccion nace
``pending`` para revision humana.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import uuid
from datetime import date
from pathlib import Path
from typing import Any, cast

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.api.fiscal_year_guard import require_open_fiscal_year
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.domain.mixed_expenses import transaction_allocation
from app.models.entities import (
    Account,
    AuditLog,
    Evidence,
    FiscalYear,
    Transaction,
    VendorAccountRule,
)
from app.models.enums import AccountCategory, TransactionSource, TransactionStatus
from app.services.fiscal_years import resolve_active_fiscal_year
from app.services.ocr import provider_statuses
from app.services.ocr.base import OCRProvider, OCRProviderUnavailableError
from app.services.ocr.parsers.reg_number import validate_checksum
from app.services.ocr.pipeline import ReceiptProcessingResult, process_receipt
from app.services.ocr.quota import usage_report
from app.services.ocr.runtime_settings import (
    TOGGLEABLE_PROVIDERS,
    apply_overrides,
    patch_overrides,
)
from app.services.vendor_rules import (
    LearnedAccountClassifier,
    learn_rule,
    normalize_vendor,
)

logger = logging.getLogger(__name__)

# Alias para usar en anotaciones de modelos cuyo campo se llama `date`
# (evita que el nombre del campo pise al tipo al evaluar `date | None`).
DateType = date

router = APIRouter(tags=["receipts"])

# Inyeccion de proveedores override-able en tests (None = usar registry).
_TEST_PROVIDERS: list[OCRProvider] | None = None


def set_test_providers(providers: list[OCRProvider] | None) -> None:
    """Inyecta una cadena de proveedores para tests (evita deps externas).

    Args:
        providers: Lista de proveedores a usar, o ``None`` para volver al
            registry normal.
    """
    global _TEST_PROVIDERS
    _TEST_PROVIDERS = providers


# --- Schemas de respuesta -------------------------------------------------


class JournalLineOut(BaseModel):
    """Linea de 仕訳 propuesta."""

    side: str
    account_code: str
    amount: int
    tax_rate: int | None = None


class JournalSuggestionOut(BaseModel):
    """仕訳 candidato propuesto por el OCR."""

    date: DateType | None
    description: str
    lines: list[JournalLineOut]
    account_code: str = Field(description="勘定科目 sugerido para el gasto")
    account_confidence: float


class TransactionOut(BaseModel):
    """Transaccion (取引) propuesta o persistida."""

    id: uuid.UUID | None
    date: DateType | None
    vendor: str | None
    total_amount: int | None
    registration_number: str | None
    is_qualified_invoice: bool
    confidence: float | None
    status: TransactionStatus
    tax_lines: list[dict[str, Any]]
    evidence_id: uuid.UUID | None = None
    account_code: str | None = None
    field_confidences: dict[str, float] | None = None
    business_allocation: dict[str, Any] | None = None


class ReceiptResponse(BaseModel):
    """Respuesta de `POST /receipts`.

    Args:
        transaction: Transaccion propuesta (siempre ``pending``).
        journal_suggestion: 仕訳 candidato.
        confidence: Confianza combinada (OCR + validacion).
        confidence_level: ``"high"`` o ``"low"``.
        provider_used: Proveedor que leyo el recibo (``"cache"`` si era duplicado
            exacto y no hizo falta volver a leerlo).
        validation_errors: Chequeos que no pasaron.
        duplicate: ``True`` si esta foto ya estaba archivada (mismo hash) y se
            devolvio la transaccion existente en vez de crear otra.
        duplicate_of: Id de la transaccion que parece ser la misma compra (mismo
            hash, o misma fecha+importe+取引先), o ``None``.
        account_source: Origen del 科目 propuesto (``learned`` = regla aprendida
            de una confirmacion anterior del mismo 取引先).
    """

    transaction: TransactionOut
    journal_suggestion: JournalSuggestionOut
    confidence: float
    confidence_level: str
    provider_used: str
    validation_errors: list[str]
    duplicate: bool = False
    duplicate_of: uuid.UUID | None = None
    account_source: str = "rule"


class EvidenceOut(BaseModel):
    """Documento archivado, sin exponer su ruta local ni hash interno."""

    id: uuid.UUID
    transaction_id: uuid.UUID
    date: DateType | None
    amount: int | None
    vendor: str | None
    archived_at: _dt.datetime
    retention_until: DateType | None
    source: TransactionSource
    status: TransactionStatus
    file_available: bool


class EvidenceListOut(BaseModel):
    """Resultado filtrado del archivo de recibos y certificados."""

    year: int
    total_count: int
    total_amount: int
    items: list[EvidenceOut]


class ProviderStatusOut(BaseModel):
    """Estado de un proveedor OCR (para el toggle on/off del frontend)."""

    name: str
    enabled: bool
    available: bool
    sends_data_externally: bool
    usable: bool
    reason: str | None = None


class ProvidersResponse(BaseModel):
    """Respuesta de `GET /ocr/providers`."""

    allow_external_ocr: bool
    primary: str
    fallback_chain: list[str]
    providers: list[ProviderStatusOut]


class UsageOut(BaseModel):
    """Uso diario de cuota de un proveedor cloud (free tier).

    Args:
        provider: Nombre del proveedor cloud.
        used_today: Requests reales hechas hoy (dia US/Pacific).
        daily_limit: Limite diario configurado (env/config).
        percent: Porcentaje usado (0-100, redondeado).
        over_limit: ``True`` si ya alcanzo el limite (no-usable hoy).
        warn: ``True`` si supero el umbral de aviso (>=80%) sin frenar aun.
        resets_at: Instante ISO (UTC) del proximo reseteo (00:00 Pacific).
    """

    provider: str
    used_today: int
    daily_limit: int
    percent: int
    over_limit: bool
    warn: bool
    resets_at: str


class UsageResponse(BaseModel):
    """Respuesta de `GET /ocr/usage`: uso por proveedor cloud."""

    providers: list[UsageOut]


class ReceiptPatch(BaseModel):
    """Campos editables de una transaccion en revision."""

    date: DateType | None = None
    vendor: str | None = None
    total_amount: int | None = None
    registration_number: str | None = None
    status: TransactionStatus | None = None
    account_code: str | None = None


class RegistrationCorrection(BaseModel):
    expected_number: str | None
    number: str = Field(pattern=r"^T[0-9]{13}$")


class AllocationRequest(BaseModel):
    expected_total: int = Field(ge=0, strict=True)
    numerator: int = Field(ge=0, le=1_000_000_000, strict=True)
    denominator: int = Field(gt=0, le=1_000_000_000, strict=True)
    rationale: str = Field(min_length=1, max_length=500)


class BatchConfirmRequest(BaseModel):
    """Pedido de confirmacion en lote."""

    transaction_ids: list[uuid.UUID]


class ConfirmRequest(BaseModel):
    """Correcciones opcionales aplicadas al confirmar (confirmacion de 1 toque).

    Permite corregir y confirmar en una sola llamada desde el celular, sin pasar
    por la bandeja: el usuario toca el 科目 correcto y confirma.

    Args:
        date: Fecha corregida, o ``None`` para dejar la leida.
        vendor: 取引先 corregido, o ``None``.
        total_amount: Importe corregido, o ``None``.
        account_code: 勘定科目 elegido, o ``None`` para aceptar el propuesto.
    """

    date: DateType | None = None
    vendor: str | None = None
    total_amount: int | None = None
    account_code: str | None = None


class VendorRuleOut(BaseModel):
    """Regla aprendida 取引先 -> 勘定科目 (para mostrarla y poder borrarla)."""

    id: uuid.UUID
    vendor_key: str
    vendor_sample: str | None
    account_code: str
    hits: int
    last_used_at: _dt.datetime


class OcrSettingsPatch(BaseModel):
    """Cambios parciales de los toggles OCR (switch maestro + proveedores).

    Args:
        allow_external_ocr: Nuevo valor del switch maestro, o ``None``.
        providers: Mapa ``{nombre: enabled}`` con los flags a actualizar (solo
            proveedores toggleables: paddle/ollama/azure/google/gemini/glm).
        daily_limits: Mapa ``{nombre: limite}`` con los limites diarios de cuota
            a ajustar (solo proveedores cloud: gemini/glm/azure/google).
    """

    allow_external_ocr: bool | None = None
    providers: dict[str, bool] | None = None
    daily_limits: dict[str, int] | None = None


# --- Helpers --------------------------------------------------------------


def _resolve_fiscal_year(
    db: Session, settings: Settings, year: int | None = None
) -> FiscalYear | None:
    """Resuelve el 年度 destino de un recibo.

    Si se pasa ``year``, devuelve ese 年度 concreto (o ``None`` si no existe).
    Si no se pasa, cae al 年度 OPEN más reciente (no ciegamente el último), para
    que los recibos se registren en el año activo del ciclo multi-año.

    Args:
        db: Sesión de BD.
        settings: Settings (reservado para futuras reglas por año).
        year: Año fiscal destino explícito, o ``None`` para el activo.

    Returns:
        El `FiscalYear` resuelto, o ``None`` si no hay un 年度 aplicable.
    """
    if year is not None:
        return db.scalars(
            select(FiscalYear).where(FiscalYear.year == year)
        ).first()
    return resolve_active_fiscal_year(db)


def _store_evidence(
    db: Session,
    *,
    image_bytes: bytes,
    settings: Settings,
    result: ReceiptProcessingResult,
    digest: str | None = None,
) -> Evidence:
    """Archiva la imagen como `Evidence` (hash, timestamp, indices 電帳法).

    Args:
        db: Sesion de SQLAlchemy.
        image_bytes: Bytes originales del recibo (≥200dpi esperado).
        settings: Settings (carpeta de evidencia).
        result: Resultado del pipeline (para los indices 日付/金額/取引先).
        digest: SHA-256 ya calculado de ``image_bytes`` (evita recalcularlo).

    Returns:
        `Evidence` persistida (flush, sin commit).
    """
    digest = digest or hashlib.sha256(image_bytes).hexdigest()
    evidence_dir = Path(settings.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    file_ref = str(evidence_dir / f"{digest}.bin")
    # Guardar el original solo si no existe (idempotente por hash).
    target = Path(file_ref)
    if not target.exists():
        target.write_bytes(image_bytes)

    retention = None
    if result.parsed.date:
        retention = date(result.parsed.date.year + 7, result.parsed.date.month, 1)

    evidence = Evidence(
        file_ref=file_ref,
        hash=digest,
        timestamp=_dt.datetime.now(_dt.UTC),
        idx_date=result.parsed.date,
        idx_amount=result.parsed.total,
        idx_vendor=result.parsed.vendor,
        retention_until=retention,
    )
    db.add(evidence)
    db.flush()
    return evidence


def _evidence_file_path(evidence: Evidence, settings: Settings) -> Path | None:
    """Resuelve un archivo solo si permanece dentro del almacén configurado."""
    base = Path(settings.evidence_dir).resolve()
    candidate = Path(evidence.file_ref).resolve()
    if not candidate.is_relative_to(base) or not candidate.is_file():
        return None
    return candidate


def _find_duplicate_by_hash(
    db: Session, *, digest: str, fiscal_year_id: uuid.UUID
) -> Transaction | None:
    """Busca una transaccion del mismo 年度 creada desde esta misma imagen.

    Sacar dos veces la foto del mismo recibo es lo mas comun en el celular. Como
    la evidencia se archiva por hash, un hash repetido en el mismo 年度 significa
    que ese recibo ya esta cargado.

    Args:
        db: Sesion de BD.
        digest: SHA-256 de los bytes subidos.
        fiscal_year_id: 年度 destino.

    Returns:
        La `Transaction` existente, o ``None`` si es una imagen nueva.
    """
    return db.scalars(
        select(Transaction)
        .join(Evidence, Transaction.evidence_id == Evidence.id)
        .where(
            Evidence.hash == digest,
            Transaction.fiscal_year_id == fiscal_year_id,
        )
        .order_by(Transaction.created_at.desc())
    ).first()


def _find_soft_duplicate(
    db: Session,
    *,
    fiscal_year_id: uuid.UUID,
    tx_date: date | None,
    total: int | None,
    vendor: str | None,
    exclude_id: uuid.UUID | None = None,
) -> Transaction | None:
    """Busca una compra ya cargada que coincide en fecha, importe y 取引先.

    Cubre el caso de la misma compra fotografiada dos veces (foto distinta, mismo
    ticket) o cargada tambien por CSV de tarjeta. No bloquea nada: solo alimenta
    el aviso de la UI.

    Args:
        db: Sesion de BD.
        fiscal_year_id: 年度 destino.
        tx_date: Fecha leida del recibo.
        total: Importe total leido.
        vendor: 取引先 leido.
        exclude_id: Transaccion a excluir (la recien creada).

    Returns:
        La `Transaction` candidata a duplicado, o ``None``.
    """
    if tx_date is None or not total:
        return None
    stmt = select(Transaction).where(
        Transaction.fiscal_year_id == fiscal_year_id,
        Transaction.date == tx_date,
        Transaction.total_amount == total,
    )
    if exclude_id is not None:
        stmt = stmt.where(Transaction.id != exclude_id)
    for candidate in db.scalars(stmt).all():
        if normalize_vendor(candidate.vendor) == normalize_vendor(vendor):
            return candidate
    return None


def _journal_from_transaction(tx: Transaction) -> JournalSuggestionOut:
    """Reconstruye el 仕訳 candidato de una transaccion ya persistida.

    Se usa en la respuesta del duplicado exacto, donde no se vuelve a correr el
    OCR (asi la segunda foto del mismo ticket no gasta cuota cloud).

    Args:
        tx: Transaccion existente.

    Returns:
        `JournalSuggestionOut` equivalente al que propuso el pipeline.
    """
    account_code = tx.account_code or "599"
    tax_lines = cast("list[dict[str, Any]]", tx.tax_lines or [])
    lines: list[JournalLineOut] = []
    debit_sum = 0
    if tax_lines and all(
        tl.get("base") is not None and tl.get("tax") is not None for tl in tax_lines
    ):
        for tl in tax_lines:
            amount = int(tl.get("base") or 0) + int(tl.get("tax") or 0)
            debit_sum += amount
            rate = tl.get("rate")
            lines.append(
                JournalLineOut(
                    side="debit",
                    account_code=account_code,
                    amount=amount,
                    tax_rate=int(rate) if rate is not None else None,
                )
            )
    else:
        debit_sum = tx.total_amount
        lines.append(
            JournalLineOut(side="debit", account_code=account_code, amount=debit_sum)
        )
    lines.append(JournalLineOut(side="credit", account_code="312", amount=debit_sum))
    return JournalSuggestionOut(
        date=tx.date,
        description=tx.vendor or "OCR 領収書",
        lines=lines,
        account_code=account_code,
        account_confidence=tx.confidence or 0.0,
    )


def _to_transaction_out(tx: Transaction) -> TransactionOut:
    """Serializa una `Transaction` persistida a `TransactionOut`."""
    return TransactionOut(
        id=tx.id,
        date=tx.date,
        vendor=tx.vendor,
        total_amount=tx.total_amount,
        registration_number=tx.registration_number,
        is_qualified_invoice=tx.is_qualified_invoice,
        confidence=tx.confidence,
        status=tx.status,
        tax_lines=tx.tax_lines or [],
        evidence_id=tx.evidence_id,
        account_code=tx.account_code,
        field_confidences=cast("dict[str, float] | None", tx.field_confidences),
        business_allocation=cast("dict[str, Any] | None", tx.business_allocation),
    )


# --- Endpoints ------------------------------------------------------------


class ManualExpenseRequest(BaseModel):
    year: int = Field(ge=2000, le=2100)
    date: DateType
    vendor: str = Field(min_length=1, max_length=255)
    total_amount: int = Field(gt=0, le=2_000_000_000)
    account_code: str = Field(min_length=1, max_length=32)


@router.post("/receipts/manual", response_model=TransactionOut, status_code=201)
def create_manual_expense(
    payload: ManualExpenseRequest, db: Session = Depends(get_db)
) -> TransactionOut:
    """Guarda un gasto para revisión; no crea ni inventa un comprobante."""
    fiscal_year = _resolve_fiscal_year(db, get_settings(), payload.year)
    if fiscal_year is None:
        raise HTTPException(status_code=404, detail="年度が見つかりません。")
    require_open_fiscal_year(fiscal_year)
    if payload.date.year != fiscal_year.year:
        raise HTTPException(status_code=422, detail="日付が選択した年度と一致しません。")
    vendor = payload.vendor.strip()
    if not vendor:
        raise HTTPException(status_code=422, detail="取引先を入力してください。")
    account = db.scalar(
        select(Account).where(
            Account.code == payload.account_code, Account.category == AccountCategory.EXPENSE
        )
    )
    if account is None:
        raise HTTPException(status_code=422, detail="有効な経費科目を選択してください。")
    tx = Transaction(
        fiscal_year_id=fiscal_year.id,
        date=payload.date,
        vendor=vendor,
        total_amount=payload.total_amount,
        account_code=account.code,
        source=TransactionSource.MANUAL,
        status=TransactionStatus.PENDING,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return _to_transaction_out(tx)


@router.post("/receipts", response_model=ReceiptResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    fiscal_year_id: uuid.UUID | None = Form(default=None),
    year: int | None = Form(default=None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ReceiptResponse:
    """Sube un recibo, corre el OCR y propone un 仕訳.

    Args:
        file: Imagen o PDF del recibo (multipart).
        fiscal_year_id: 年度 destino (opcional; usa el ultimo abierto si falta).
        year: Año destino explícito usado por el selector del frontend.
        db: Sesion de BD.
        settings: Settings.

    Returns:
        `ReceiptResponse` con la transaccion (pending), el 仕訳 candidato y la
        confianza/proveedor usado.

    Raises:
        HTTPException: 400 si la imagen esta vacia; 422 si no hay 年度;
            503 si no hay proveedores OCR usables.
    """
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_file", "message": "El archivo esta vacio.", "details": {}},
        )

    fiscal_year = (
        db.get(FiscalYear, fiscal_year_id)
        if fiscal_year_id is not None
        else _resolve_fiscal_year(db, settings, year)
    )
    if fiscal_year is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "no_fiscal_year",
                "message": "No hay un 年度 abierto para registrar la transaccion.",
                "details": {},
            },
        )
    require_open_fiscal_year(fiscal_year)

    # Duplicado exacto: la misma foto ya archivada en este 年度. Se devuelve la
    # transaccion existente sin volver a leerla (no gasta cuota cloud ni duplica
    # el gasto). Es el error mas comun sacando fotos en la calle.
    digest = hashlib.sha256(image_bytes).hexdigest()
    existing = _find_duplicate_by_hash(
        db, digest=digest, fiscal_year_id=fiscal_year.id
    )
    if existing is not None:
        return ReceiptResponse(
            transaction=_to_transaction_out(existing),
            journal_suggestion=_journal_from_transaction(existing),
            confidence=existing.confidence or 0.0,
            confidence_level="high" if (existing.confidence or 0.0) >= 0.75 else "low",
            provider_used="cache",
            validation_errors=[],
            duplicate=True,
            duplicate_of=existing.id,
            account_source="learned" if existing.account_code else "rule",
        )

    try:
        result = process_receipt(
            image_bytes,
            providers=_TEST_PROVIDERS,
            classifier=LearnedAccountClassifier(db),
        )
    except OCRProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ocr_unavailable",
                "message": "No hay proveedores OCR usables.",
                "details": {"reason": str(exc)},
            },
        ) from exc

    evidence = _store_evidence(
        db, image_bytes=image_bytes, settings=settings, result=result, digest=digest
    )

    tx = Transaction(
        fiscal_year_id=fiscal_year.id,
        date=result.parsed.date or date.today(),
        vendor=result.parsed.vendor,
        total_amount=result.parsed.total or 0,
        source=TransactionSource.OCR,
        evidence_id=evidence.id,
        registration_number=result.parsed.registration_number,
        is_qualified_invoice=result.parsed.is_qualified_invoice,
        confidence=result.overall_confidence,
        status=result.status,  # siempre pending (nunca auto-registra)
        tax_lines=result.parsed.tax_lines,
        account_code=result.account_suggestion.account_code,
        field_confidences=result.parsed.field_confidences or None,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    journal = JournalSuggestionOut(
        date=result.journal_candidate.date,
        description=result.journal_candidate.description,
        lines=[
            JournalLineOut(
                side=ln.side,
                account_code=ln.account_code,
                amount=ln.amount,
                tax_rate=ln.tax_rate,
            )
            for ln in result.journal_candidate.lines
        ],
        account_code=result.account_suggestion.account_code,
        account_confidence=result.account_suggestion.confidence,
    )

    # Duplicado "blando": misma fecha + importe + 取引先 ya cargados (misma compra
    # fotografiada dos veces, o tambien importada del CSV de la tarjeta).
    soft = _find_soft_duplicate(
        db,
        fiscal_year_id=fiscal_year.id,
        tx_date=tx.date,
        total=tx.total_amount,
        vendor=tx.vendor,
        exclude_id=tx.id,
    )

    return ReceiptResponse(
        transaction=_to_transaction_out(tx),
        journal_suggestion=journal,
        confidence=result.overall_confidence,
        confidence_level=result.confidence_level,
        provider_used=result.provider_used,
        validation_errors=result.validation.errors,
        duplicate=False,
        duplicate_of=soft.id if soft is not None else None,
        account_source=result.account_suggestion.source,
    )


@router.get("/receipts", response_model=list[TransactionOut])
def list_receipts(
    status: TransactionStatus | None = None,
    year: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    """Lista transacciones de la bandeja de 仕訳, opcionalmente por estado.

    Incluye los 仕訳 candidatos de OCR (recibos) y de import CSV (banco/tarjeta):
    ambos comparten la misma bandeja de revision. Los asientos puramente
    manuales pendientes también requieren revisión.

    Filtra por 年度 para no mezclar años en la bandeja: con ``year`` explícito usa
    ese año; sin él, usa el 年度 OPEN más reciente (año activo del ciclo). Si no
    hay ningún 年度 aplicable, devuelve lista vacía.

    Args:
        status: Filtro de estado (ej. ``pending`` para la bandeja de revision).
        year: 年度 a filtrar (opcional; default = OPEN más reciente).
        db: Sesion de BD.

    Returns:
        Lista de `TransactionOut` del 年度 resuelto.
    """
    fiscal_year = _resolve_fiscal_year(db, get_settings(), year)
    if fiscal_year is None:
        return []
    tray_sources = (
        TransactionSource.OCR,
        TransactionSource.CSV,
        TransactionSource.BANK,
        TransactionSource.MANUAL,
    )
    stmt = select(Transaction).where(
        Transaction.source.in_(tray_sources),
        Transaction.fiscal_year_id == fiscal_year.id,
    )
    if status is not None:
        stmt = stmt.where(Transaction.status == status)
    stmt = stmt.order_by(Transaction.date.desc())
    return [_to_transaction_out(tx) for tx in db.scalars(stmt).all()]


@router.get("/evidence", response_model=EvidenceListOut)
def list_evidence(
    year: int = Query(default=2025, ge=2000, le=2100),
    vendor: str | None = Query(default=None, max_length=255),
    date_from: DateType | None = Query(default=None),
    date_to: DateType | None = Query(default=None),
    amount_min: int | None = Query(default=None, ge=0),
    amount_max: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EvidenceListOut:
    """Busca comprobantes OCR archivados por los índices exigidos por 電帳法."""
    conditions = [FiscalYear.year == year]
    if vendor and vendor.strip():
        conditions.append(Evidence.idx_vendor.ilike(f"%{vendor.strip()}%"))
    if date_from is not None:
        conditions.append(Evidence.idx_date >= date_from)
    if date_to is not None:
        conditions.append(Evidence.idx_date <= date_to)
    if amount_min is not None:
        conditions.append(Evidence.idx_amount >= amount_min)
    if amount_max is not None:
        conditions.append(Evidence.idx_amount <= amount_max)

    joins = (
        (Transaction, Transaction.evidence_id == Evidence.id),
        (FiscalYear, Transaction.fiscal_year_id == FiscalYear.id),
    )
    summary_stmt = select(
        func.count(Evidence.id), func.coalesce(func.sum(Evidence.idx_amount), 0)
    ).select_from(Evidence)
    rows_stmt = select(Evidence, Transaction).select_from(Evidence)
    for model, on_clause in joins:
        summary_stmt = summary_stmt.join(model, on_clause)
        rows_stmt = rows_stmt.join(model, on_clause)

    total_count, total_amount = db.execute(summary_stmt.where(*conditions)).one()
    rows = db.execute(
        rows_stmt.where(*conditions)
        .order_by(Evidence.idx_date.desc(), Evidence.timestamp.desc())
        .limit(limit)
    ).all()
    return EvidenceListOut(
        year=year,
        total_count=int(total_count),
        # COALESCE ya garantiza 0 en SQL; el tipo estático hereda `int | None` de idx_amount.
        total_amount=int(total_amount or 0),
        items=[
            EvidenceOut(
                id=evidence.id,
                transaction_id=transaction.id,
                date=evidence.idx_date,
                amount=evidence.idx_amount,
                vendor=evidence.idx_vendor,
                archived_at=evidence.timestamp,
                retention_until=evidence.retention_until,
                source=TransactionSource(transaction.source),
                status=TransactionStatus(transaction.status),
                file_available=_evidence_file_path(evidence, settings) is not None,
            )
            for evidence, transaction in rows
        ],
    )


@router.get("/evidence/{evidence_id}/file")
def download_evidence(
    evidence_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Descarga el original archivado sin revelar ni aceptar rutas del cliente."""
    evidence = db.get(Evidence, evidence_id)
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": "保存書類が見つかりませんでした。",
                "details": {},
            },
        )
    path = _evidence_file_path(evidence, settings)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "evidence_file_missing",
                "message": "保存書類のファイルが保存先に見つかりませんでした。",
                "details": {},
            },
        )
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"evidence-{evidence.id}.bin",
    )


def _get_tx_or_404(db: Session, transaction_id: uuid.UUID) -> Transaction:
    """Devuelve la transaccion o lanza 404."""
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Transaccion no encontrada.", "details": {}},
        )
    return tx


@router.put("/receipts/{transaction_id}/business-allocation", response_model=TransactionOut)
def set_business_allocation(
    transaction_id: uuid.UUID, payload: AllocationRequest, db: Session = Depends(get_db)
) -> TransactionOut:
    """Guarda un criterio revisado sin alterar el total original del recibo."""
    tx = _get_tx_or_404(db, transaction_id)
    require_open_fiscal_year(tx.fiscal_year)
    if tx.status != TransactionStatus.PENDING:
        raise HTTPException(status_code=409, detail="Solo se puede repartir un gasto pendiente.")
    if payload.expected_total != tx.total_amount:
        raise HTTPException(
            status_code=409, detail="El importe cambió; vuelve a revisar el recibo."
        )
    rationale = payload.rationale.strip()
    if not rationale:
        raise HTTPException(status_code=422, detail="Explica el criterio de reparto.")
    before = tx.business_allocation
    tx.business_allocation = {
        "original_total": tx.total_amount,
        "numerator": payload.numerator,
        "denominator": payload.denominator,
        "rationale": rationale,
    }
    try:
        transaction_allocation(tx)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.add(AuditLog(entity="transaction", entity_id=str(tx.id), action="allocate",
                    before=before, after=tx.business_allocation))
    db.commit()
    db.refresh(tx)
    return _to_transaction_out(tx)


@router.post("/receipts/{transaction_id}/confirm", response_model=TransactionOut)
def confirm_receipt(
    transaction_id: uuid.UUID,
    corrections: ConfirmRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> TransactionOut:
    """Confirma una transaccion propuesta, con correcciones opcionales.

    Confirmacion de 1 toque desde el celular: si el usuario corrige el 科目 (o
    fecha/取引先/importe) lo manda en el mismo request, y la app **aprende** la
    regla del 取引先 para que la proxima foto de esa tienda ya venga bien.

    Args:
        transaction_id: Id de la transaccion.
        corrections: Correcciones a aplicar antes de confirmar (opcional).
        db: Sesion de BD.

    Returns:
        `TransactionOut` actualizada.
    """
    tx = _get_tx_or_404(db, transaction_id)
    require_open_fiscal_year(tx.fiscal_year)
    if corrections is not None:
        if (
            tx.business_allocation is not None
            and corrections.total_amount not in (None, tx.total_amount)
        ):
            raise HTTPException(status_code=409, detail="El reparto requiere el importe original.")
        for field_name, value in corrections.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(tx, field_name, value)
    tx.status = TransactionStatus.CONFIRMED
    learn_rule(db, tx.vendor, tx.account_code)
    db.commit()
    db.refresh(tx)
    return _to_transaction_out(tx)


@router.patch("/receipts/{transaction_id}", response_model=TransactionOut)
def patch_receipt(
    transaction_id: uuid.UUID, patch: ReceiptPatch, db: Session = Depends(get_db)
) -> TransactionOut:
    """Edita campos extraidos de una transaccion en revision.

    Args:
        transaction_id: Id de la transaccion.
        patch: Campos a actualizar (solo los provistos).
        db: Sesion de BD.

    Returns:
        `TransactionOut` actualizada.
    """
    tx = _get_tx_or_404(db, transaction_id)
    require_open_fiscal_year(tx.fiscal_year)
    data = patch.model_dump(exclude_unset=True)
    if "registration_number" in data:
        raise HTTPException(status_code=422, detail="Usa la corrección de 登録番号 con revisión.")
    if (
        tx.business_allocation is not None
        and data.get("total_amount", tx.total_amount) != tx.total_amount
    ):
        raise HTTPException(status_code=409, detail="El reparto requiere el importe original.")
    for field_name, value in data.items():
        setattr(tx, field_name, value)
    db.commit()
    db.refresh(tx)
    return _to_transaction_out(tx)


@router.put("/receipts/{transaction_id}/registration-number", response_model=TransactionOut)
def correct_registration_number(
    transaction_id: uuid.UUID, payload: RegistrationCorrection, db: Session = Depends(get_db)
) -> TransactionOut:
    """Corrige el texto OCR pendiente, sin verificar la inscripción del emisor."""
    tx = _get_tx_or_404(db, transaction_id)
    require_open_fiscal_year(tx.fiscal_year)
    if tx.status != TransactionStatus.PENDING or tx.registration_number != payload.expected_number:
        raise HTTPException(status_code=409, detail="El recibo cambió o ya no está pendiente.")
    previous = {"registration_number": tx.registration_number,
                "is_qualified_invoice": tx.is_qualified_invoice}
    candidate = validate_checksum(payload.number[1:])
    result = cast(CursorResult[Any], db.execute(update(Transaction).where(
        Transaction.id == transaction_id, Transaction.status == TransactionStatus.PENDING,
        Transaction.registration_number.is_(None) if payload.expected_number is None
        else Transaction.registration_number == payload.expected_number,
    ).values(registration_number=payload.number, is_qualified_invoice=candidate)))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="El recibo cambió. Actualiza y vuelve a revisar."
        )
    db.add(AuditLog(
        entity="transaction", entity_id=str(transaction_id), action="correct_reg_number",
        before=previous, after={"registration_number": payload.number,
                                "is_qualified_invoice": candidate},
    ))
    db.commit()
    db.refresh(tx)
    return _to_transaction_out(tx)


@router.post("/receipts/batch-confirm", response_model=list[TransactionOut])
def batch_confirm(
    payload: BatchConfirmRequest, db: Session = Depends(get_db)
) -> list[TransactionOut]:
    """Confirma varias transacciones a la vez (batch review).

    Args:
        payload: Lista de ids a confirmar.
        db: Sesion de BD.

    Returns:
        Lista de `TransactionOut` confirmadas.
    """
    transactions: list[Transaction] = []
    for tx_id in payload.transaction_ids:
        tx = db.get(Transaction, tx_id)
        if tx is not None:
            transactions.append(tx)
    for tx in transactions:
        require_open_fiscal_year(tx.fiscal_year)

    confirmed: list[TransactionOut] = []
    for tx in transactions:
        tx.status = TransactionStatus.CONFIRMED
        learn_rule(db, tx.vendor, tx.account_code)
        confirmed.append(_to_transaction_out(tx))
    db.commit()
    return confirmed


@router.get("/receipts/vendor-rules", response_model=list[VendorRuleOut])
def list_vendor_rules(db: Session = Depends(get_db)) -> list[VendorRuleOut]:
    """Lista las reglas 取引先 -> 勘定科目 que la app aprendio.

    El aprendizaje es visible y reversible a proposito: el usuario ve por que se
    le propone cada 科目 y puede borrar una regla que quedo mal.

    Args:
        db: Sesion de BD.

    Returns:
        Reglas ordenadas por uso reciente.
    """
    rules = db.scalars(
        select(VendorAccountRule).order_by(VendorAccountRule.last_used_at.desc())
    ).all()
    return [
        VendorRuleOut(
            id=rule.id,
            vendor_key=rule.vendor_key,
            vendor_sample=rule.vendor_sample,
            account_code=rule.account_code,
            hits=rule.hits,
            last_used_at=rule.last_used_at,
        )
        for rule in rules
    ]


@router.delete("/receipts/vendor-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vendor_rule(rule_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    """Borra una regla aprendida (el 取引先 vuelve al mapeo por defecto).

    Args:
        rule_id: Id de la regla.
        db: Sesion de BD.

    Raises:
        HTTPException: 404 si la regla no existe.
    """
    rule = db.get(VendorAccountRule, rule_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": "学習ルールが見つかりませんでした。",
                "details": {},
            },
        )
    db.delete(rule)
    db.commit()


@router.get("/ocr/providers", response_model=ProvidersResponse)
def get_ocr_providers(settings: Settings = Depends(get_settings)) -> ProvidersResponse:
    """Lista el estado de los proveedores OCR (toggle on/off del frontend).

    Args:
        settings: Settings.

    Returns:
        `ProvidersResponse` con consentimiento, primario, fallback y estados.
    """
    effective = apply_overrides(settings)
    statuses = provider_statuses(effective)
    return ProvidersResponse(
        allow_external_ocr=effective.allow_external_ocr,
        primary=effective.ocr_primary,
        fallback_chain=effective.ocr_fallback_chain,
        providers=[
            ProviderStatusOut(
                name=s.name,
                enabled=s.enabled,
                available=s.available,
                sends_data_externally=s.sends_data_externally,
                usable=s.usable,
                reason=s.reason,
            )
            for s in statuses
        ],
    )


@router.get("/ocr/usage", response_model=UsageResponse)
def get_ocr_usage(settings: Settings = Depends(get_settings)) -> UsageResponse:
    """Devuelve el uso diario de cuota de cada proveedor cloud (free tier).

    Cuenta las requests reales del dia (zona US/Pacific, como resetea Google) y
    expone el limite configurado, el porcentaje, el aviso al 80% y cuando se
    resetea. Lo usa el contador del Settings (設定) del frontend.

    Args:
        settings: Settings.

    Returns:
        `UsageResponse` con un `UsageOut` por proveedor cloud.
    """
    effective = apply_overrides(settings)
    return UsageResponse(
        providers=[UsageOut(**row) for row in usage_report(settings=effective)]
    )


@router.patch("/ocr/providers", response_model=ProvidersResponse)
def patch_ocr_providers(
    patch: OcrSettingsPatch, settings: Settings = Depends(get_settings)
) -> ProvidersResponse:
    """Aplica y persiste cambios de los toggles OCR (runtime, sin reiniciar).

    Persiste el switch maestro ``allow_external_ocr`` y los flags ``enabled``
    por proveedor en un override en disco que se superpone a la config base.
    Las credenciales nunca se tocan por aca (solo por env). La logica de
    consentimiento se respeta: con ``allow_external_ocr=False`` los proveedores
    cloud quedan no-usables aunque esten ``enabled``.

    Args:
        patch: Cambios parciales (switch maestro y/o flags por proveedor).
        settings: Settings base.

    Returns:
        `ProvidersResponse` con el estado ya actualizado.

    Raises:
        HTTPException: 400 si se intenta togglear un proveedor desconocido.
    """
    try:
        patch_overrides(
            allow_external_ocr=patch.allow_external_ocr,
            providers=patch.providers,
            daily_limits=patch.daily_limits,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_provider",
                "message": str(exc),
                "details": {"toggleable": list(TOGGLEABLE_PROVIDERS)},
            },
        ) from exc
    return get_ocr_providers(settings)
