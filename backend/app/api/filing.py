"""Router del 確定申告 — generacion de formularios y export e-Tax (Fase 3B-2).

Endpoints (bajo `/api/v1`):

- ``POST /filing/draft?year=2025``        — arma el FilingDraft (calculo completo
  con 仕訳 confirmados + 控除) y devuelve el resumen estructurado.
- ``GET  /filing/{id}/summary``           — resumen para revision humana.
- ``GET  /filing/{id}/pdf?form=...``      — PDF de un formulario (StreamingResponse).
- ``GET  /filing/{id}/official-package``  — ZIP con 申告書類一式 + manifiesto.
- ``GET  /filing/{id}/xtx``               — bloqueado hasta verificar el XSD.
- ``GET  /filing/{id}/csv``               — CSV (SHIFT-JIS) del 決算書.

⚠️ Realismo (research 04 §6): la app GENERA archivos; **no envia a e-Tax** (no
hay API publica de envio). El XTX permanece bloqueado hasta verificar el XSD;
los PDF son borradores que requieren revisión. Esta herramienta es de apoyo, no 税務代理.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.api.fiscal_year_guard import require_open_fiscal_year
from app.db.session import get_db
from app.models.entities import AuditLog, FilingDraft, FiscalYear, JournalEntry
from app.models.enums import FilingType
from app.services.forms.chobo import render_motocho_pdf, render_shiwakecho_pdf
from app.services.forms.drafting import PROJECTION_CREATED_BY, FilingDraftResult, build_filing_draft
from app.services.forms.etax_export import build_kessansho_csv, build_xtx
from app.services.forms.etax_validator import validate_xtx
from app.services.forms.kessansho import render_kessansho_pdf
from app.services.forms.kessansho_official import render_kessansho_official
from app.services.forms.official_package import build_official_package
from app.services.forms.shinkokusho import render_shinkokusho_pdf
from app.services.forms.shinkokusho_official import render_shinkokusho_official
from app.services.forms.shushi_official import render_shushi_official
from app.services.tax_rules import load_tax_rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/filing", tags=["filing"])

# Formularios PDF disponibles (form= del endpoint /pdf).
_PDF_FORMS = {"shinkokusho", "kessansho", "shiwakecho", "motocho"}


# --- Schemas de respuesta -------------------------------------------------


class IncomeLineOut(BaseModel):
    """Una linea del desglose de 所得."""

    kind: str
    label: str | None
    amount: int


class DeductionLineOut(BaseModel):
    """Una 控除 que entro al calculo (para el detalle "que se aplico")."""

    type: str
    amount: int


class ChecklistItemOut(BaseModel):
    """Item de la lista de prontitud."""

    key: str
    label: str
    done: bool
    detail: str | None = None


class ResidentTaxOut(BaseModel):
    """Estimacion del 住民税 (impuesto de residencia, pago futuro jun-may).

    Args:
        total_income: 合計所得金額 (reusado del 所得税).
        kiso_kojo: 基礎控除 住民税 (¥430,000 en 令和7).
        dependent_deduction: 扶養控除 住民税 total.
        resident_deductions_total: Σ所得控除 del 住民税.
        taxable_income: 課税所得(住民).
        shotokuwari_prefectural: 所得割 県民税 (4%).
        shotokuwari_municipal: 所得割 市民税 (6%).
        shotokuwari_total: 所得割 total.
        kintowari_prefectural: 均等割 県民税.
        kintowari_municipal: 均等割 市民税.
        forest_environment_tax: 森林環境税 (¥1,000 国税).
        kintowari_total: 均等割 total.
        chosei_kojo: 調整控除.
        total: 住民税 estimado total.
    """

    total_income: int
    kiso_kojo: int
    dependent_deduction: int
    resident_deductions_total: int
    taxable_income: int
    shotokuwari_prefectural: int
    shotokuwari_municipal: int
    shotokuwari_total: int
    kintowari_prefectural: int
    kintowari_municipal: int
    forest_environment_tax: int
    kintowari_total: int
    chosei_kojo: int
    total: int


class FilingSummaryOut(BaseModel):
    """Resumen estructurado del 確定申告 (todos los numeros para revision).

    Args:
        draft_id: Id del `FilingDraft`.
        year: 年度.
        filing_type: Modalidad.
        taxpayer_name: Nombre del contribuyente.
        sales_revenue: 売上(収入)金額.
        confirmed_expense_total: Σ gastos confirmados.
        confirmed_count: Nro de 仕訳 confirmados.
        pending_count: Nro de 仕訳 pending (avisar).
        aoiro_deduction: 青色申告特別控除.
        business_income: 事業所得.
        income_breakdown: Desglose de 所得.
        total_income: 合計所得金額.
        total_income_deductions: 所得控除の合計.
        taxable_income: 課税所得.
        income_tax_base: 基準所得税額.
        income_tax_after_credits: 差引所得税額.
        reconstruction_tax: 復興特別所得税.
        total_tax: 年税額.
        withholding_total: 源泉徴収・予定納税.
        final_amount: 納付額 (>0) / 還付金 (<0).
        is_refund: ``True`` si hay 還付金.
        resident_tax: Estimacion del 住民税 (pago futuro, NO 還付).
        pl_net_income: 損益計算書 差引金額.
        bs_balanced: ``True`` si el 貸借対照表 cuadra.
        deductions_applied: 控除 que entraron.
        checklist: Lista de prontitud.
    """

    draft_id: uuid.UUID
    year: int
    filing_type: str
    taxpayer_name: str
    sales_revenue: int
    confirmed_expense_total: int
    confirmed_count: int
    pending_count: int
    aoiro_deduction: int
    business_income: int
    income_breakdown: list[IncomeLineOut]
    total_income: int
    total_income_deductions: int
    taxable_income: int
    income_tax_base: int
    income_tax_after_credits: int
    reconstruction_tax: int
    total_tax: int
    withholding_total: int
    final_amount: int
    is_refund: bool
    resident_tax: ResidentTaxOut
    pl_net_income: int
    bs_balanced: bool
    deductions_applied: list[DeductionLineOut]
    checklist: list[ChecklistItemOut]


# --- Helpers --------------------------------------------------------------


def _to_summary_out(result: FilingDraftResult) -> FilingSummaryOut:
    """Serializa un `FilingDraftResult` a `FilingSummaryOut`.

    Args:
        result: Resultado del ensamblado.

    Returns:
        El resumen estructurado para la API.
    """
    tax = result.tax
    return FilingSummaryOut(
        draft_id=result.draft_id,
        year=result.year,
        filing_type=result.filing_type,
        taxpayer_name=result.taxpayer_name,
        sales_revenue=result.sales_revenue,
        confirmed_expense_total=result.confirmed_expense_total,
        confirmed_count=result.confirmed_count,
        pending_count=result.pending_count,
        aoiro_deduction=result.aoiro_deduction,
        business_income=result.business_income,
        income_breakdown=[
            IncomeLineOut(kind=i.kind, label=i.label, amount=i.amount)
            for i in tax.income_breakdown
        ],
        total_income=tax.total_income,
        total_income_deductions=tax.total_income_deductions,
        taxable_income=tax.taxable_income,
        income_tax_base=tax.income_tax_base,
        income_tax_after_credits=tax.income_tax_after_credits,
        reconstruction_tax=tax.reconstruction_tax,
        total_tax=tax.total_tax,
        withholding_total=tax.withholding_total,
        final_amount=tax.final_amount,
        is_refund=tax.final_amount < 0,
        resident_tax=ResidentTaxOut(
            total_income=result.resident_tax.total_income,
            kiso_kojo=result.resident_tax.kiso_kojo,
            dependent_deduction=result.resident_tax.dependent_deduction,
            resident_deductions_total=result.resident_tax.resident_deductions_total,
            taxable_income=result.resident_tax.taxable_income,
            shotokuwari_prefectural=result.resident_tax.shotokuwari_prefectural,
            shotokuwari_municipal=result.resident_tax.shotokuwari_municipal,
            shotokuwari_total=result.resident_tax.shotokuwari_total,
            kintowari_prefectural=result.resident_tax.kintowari_prefectural,
            kintowari_municipal=result.resident_tax.kintowari_municipal,
            forest_environment_tax=result.resident_tax.forest_environment_tax,
            kintowari_total=result.resident_tax.kintowari_total,
            chosei_kojo=result.resident_tax.chosei_kojo,
            total=result.resident_tax.total,
        ),
        pl_net_income=result.income_statement.net_income,
        bs_balanced=result.balance_sheet.is_balanced,
        deductions_applied=[
            DeductionLineOut(type=str(d.type), amount=d.amount)
            for d in result.deductions
        ],
        checklist=[
            ChecklistItemOut(key=c.key, label=c.label, done=c.done, detail=c.detail)
            for c in result.checklist
        ],
    )


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


def _draft_or_404(db: Session, draft_id: uuid.UUID) -> FilingDraft:
    """Devuelve el `FilingDraft` o lanza 404."""
    draft = db.get(FilingDraft, draft_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "draft_not_found",
                "message": "申告書ドラフトが見つかりませんでした。",
                "details": {},
            },
        )
    return draft


def _rebuild_for_draft(db: Session, draft: FilingDraft) -> tuple[FilingDraftResult, FiscalYear]:
    """Recalcula el `FilingDraftResult` y el 年度 de un draft persistido.

    El draft persiste solo un snapshot ligero; para renderizar necesitamos el
    resultado completo (PL/BS/calculo), que se reconstruye de forma determinista
    desde los mismos datos del 年度.

    Args:
        db: Sesion de BD.
        draft: `FilingDraft` persistido.

    Returns:
        Tupla ``(FilingDraftResult, FiscalYear)``.

    Raises:
        HTTPException: 404 si el 年度 ya no existe.
    """
    fy = db.get(FiscalYear, draft.fiscal_year_id)
    if fy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "no_fiscal_year", "message": "年度が見つかりません。", "details": {}},
        )
    result = build_filing_draft(db, fy.year)
    return result, fy


def _require_verified_export(year: int) -> None:
    """No atribuir a 2026 los formatos oficiales y esquemas de 2025."""
    if year != 2025:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "filing_format_not_verified",
                "message": f"{year}年分の提出用様式は未検証のため出力できません。",
                "details": {"year": year},
            },
        )


def _require_xtx_xsd_verified() -> None:
    """Impide descargar un XML que no satisface el XSD oficial del procedimiento."""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "xtx_xsd_not_verified",
            "message": "e-Tax形式の検証が完了していないため、XTXを出力できません。",
            "details": {},
        },
    )


def _require_complete_xtx(result: FilingDraftResult) -> None:
    """Evita emitir XTX cuando el mapeo omite partidas presentes."""
    from app.services.forms.tax_office import resolve_tax_office

    profile = result.taxpayer_profile
    if not resolve_tax_office(profile.filing_office_key if profile else None).header_name:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "code": "tax_office_unrecognized",
            "message": (
                "La oficina fiscal no está configurada o no está reconocida. "
                "Revisa el formulario oficial antes de presentar."
            ),
            "details": {},
        })
    unsupported_income = any(
        item.kind not in {"jigyo", "kyuyo"} for item in result.tax.income_breakdown
    )
    if unsupported_income or result.tax.deduction_breakdown.other:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "xtx_incomplete_mapping",
                "message": "所得又は控除の一部が未対応のため、e-Taxファイルを出力できません。",
                "details": {},
            },
        )


# --- Endpoints ------------------------------------------------------------


def _journal_fingerprint(entry: JournalEntry) -> str:
    data = {
        "id": str(entry.id), "year_id": str(entry.fiscal_year_id), "date": entry.date.isoformat(),
        "description": entry.description, "transaction_id": str(entry.transaction_id),
        "created_by": entry.created_by,
        "lines": sorted((str(line.id), str(line.account_id), str(line.side), line.amount,
                         line.tax_rate) for line in entry.lines),
    }
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class JournalOriginChoice(BaseModel):
    origin: Literal["manual", "projection"]
    fingerprint: str = Field(min_length=64, max_length=64)
    backup_confirmed: Literal[True]


@router.get("/journal-review")
def review_unidentified_journal_entries(
    response: Response, year: int = Query(default=2025), db: Session = Depends(get_db)
) -> dict[str, object]:
    """Lista asientos sin procedencia, sin cambiar datos ni recalcular."""
    years = db.scalars(select(FiscalYear).where(FiscalYear.year == year).limit(2)).all()
    if len(years) != 1:
        raise HTTPException(status_code=404 if not years else 409, detail={
            "code": "fiscal_year_unavailable", "message": "No se encontró un ejercicio único.",
            "details": {},
        })
    entries = db.scalars(
        select(JournalEntry).where(
            JournalEntry.fiscal_year_id == years[0].id, JournalEntry.created_by.is_(None)
        ).order_by(JournalEntry.date, JournalEntry.id)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return {"year": year, "entries": [{
        "id": str(entry.id), "fingerprint": _journal_fingerprint(entry),
        "date": entry.date.isoformat(), "description": entry.description,
        "transaction_id": str(entry.transaction_id) if entry.transaction_id else None,
        "lines": [{"side": getattr(line.side, "value", line.side),
                   "account_code": line.account.code, "account_name": line.account.name,
                   "amount": line.amount}
                  for line in entry.lines],
    } for entry in entries]}


@router.post("/journal-review/{entry_id}/origin")
def set_journal_origin(
    entry_id: uuid.UUID, payload: JournalOriginChoice, year: int = Query(default=2025),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Registra la decisión explícita; no modifica líneas ni regenera asientos."""
    entry = db.scalars(
        select(JournalEntry).where(JournalEntry.id == entry_id).with_for_update()
    ).first()
    if entry is None or entry.fiscal_year.year != year:
        raise HTTPException(status_code=404, detail="Asiento no encontrado para el ejercicio.")
    require_open_fiscal_year(entry.fiscal_year)
    if entry.created_by is not None or _journal_fingerprint(entry) != payload.fingerprint:
        raise HTTPException(
            status_code=409, detail="El asiento cambió. Actualiza la lista y revísalo otra vez."
        )
    origin = "user_reviewed_manual" if payload.origin == "manual" else PROJECTION_CREATED_BY
    result = cast(CursorResult[Any], db.execute(update(JournalEntry).where(
        JournalEntry.id == entry_id, JournalEntry.created_by.is_(None)
    ).values(created_by=origin)))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="El asiento ya fue revisado.")
    db.add(AuditLog(entity="journal_entry", entity_id=str(entry_id), action="origin_review",
                    before={"created_by": None, "fingerprint": payload.fingerprint},
                    after={"created_by": origin}))
    db.commit()
    return {"id": str(entry_id), "origin": payload.origin}


@router.post("/draft", response_model=FilingSummaryOut)
def create_draft(
    year: int = Query(default=2025),
    db: Session = Depends(get_db),
) -> FilingSummaryOut:
    """Arma el `FilingDraft` del 年度 (calculo completo) y devuelve el resumen.

    Materializa los 仕訳 desde los 取引 confirmados + el 売上 del perfil, calcula
    PL/BS con el motor contable, deriva el 事業所得 (青色特別控除 incluido), corre
    el calculo fiscal con las 控除 reales y persiste el snapshot.

    Args:
        year: 年度 (令和7 = 2025).
        db: Sesion de BD.

    Returns:
        `FilingSummaryOut` con todos los numeros.

    Raises:
        HTTPException: 400 si el anio no tiene parametros; 404 si no hay 年度.
    """
    _resolve_year_or_400(year)
    try:
        result = build_filing_draft(db, year)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "no_fiscal_year",
                "message": f"{year}年度が見つかりませんでした。",
                "details": {"year": year},
            },
        ) from exc
    logger.info(
        "FilingDraft year=%s 納付額=%s confirmados=%s",
        year,
        result.tax.final_amount,
        result.confirmed_count,
    )
    return _to_summary_out(result)


@router.get("/{draft_id}/summary", response_model=FilingSummaryOut)
def get_summary(draft_id: uuid.UUID, db: Session = Depends(get_db)) -> FilingSummaryOut:
    """Devuelve el resumen del 確定申告 para revision humana.

    Args:
        draft_id: Id del `FilingDraft`.
        db: Sesion de BD.

    Returns:
        `FilingSummaryOut` (recalculado de forma determinista).
    """
    draft = _draft_or_404(db, draft_id)
    result, _ = _rebuild_for_draft(db, draft)
    return _to_summary_out(result)


def _pdf_response(content: bytes, filename: str) -> StreamingResponse:
    """Construye una respuesta PDF (StreamingResponse).

    Args:
        content: Bytes del PDF.
        filename: Nombre de archivo sugerido.

    Returns:
        `StreamingResponse` con content-type application/pdf.
    """
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{draft_id}/pdf")
def get_pdf(
    draft_id: uuid.UUID,
    form: str = Query(default="shinkokusho"),
    style: str = Query(default="official"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Genera el PDF de un formulario del 確定申告.

    Args:
        draft_id: Id del `FilingDraft`.
        form: Formulario (``shinkokusho`` / ``kessansho`` / ``shiwakecho`` /
            ``motocho``).
        style: ``"official"`` (default) estampa los valores sobre el 様式 oficial
            del NTA (para 郵送); ``"replica"`` usa la réplica dibujada por la app.
            Sólo aplica a ``shinkokusho`` por ahora; el resto usa la réplica.
        db: Sesion de BD.

    Returns:
        `StreamingResponse` con el PDF (application/pdf).

    Raises:
        HTTPException: 400 si `form` es desconocido; 404 si el draft no existe.
    """
    if form not in _PDF_FORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unknown_form",
                "message": f"未知のフォームです: {form}",
                "details": {"available": sorted(_PDF_FORMS)},
            },
        )
    draft = _draft_or_404(db, draft_id)
    result, fy = _rebuild_for_draft(db, draft)

    if form in {"shinkokusho", "kessansho"}:
        _require_verified_export(result.year)

    if form == "shinkokusho":
        if style == "official":
            try:
                content = render_shinkokusho_official(result)
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "official_template_missing", "message":
                            "公式様式がありません。提出用PDFを生成できません。", "details": {}},
                ) from exc
        else:
            content = render_shinkokusho_pdf(result)
    elif form == "kessansho":
        # 青色 → 青色申告決算書 oficial (P1+P4); 白色 → 収支内訳書 oficial (P1).
        is_aoiro = result.filing_type != FilingType.SHIROIRO.value
        if style == "official":
            try:
                content = (
                    render_kessansho_official(result)
                    if is_aoiro
                    else render_shushi_official(result)
                )
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "official_template_missing", "message":
                            "公式様式がありません。提出用PDFを生成できません。", "details": {}},
                ) from exc
        else:
            content = render_kessansho_pdf(result)
    elif form == "shiwakecho":
        content = render_shiwakecho_pdf(db, fy, result)
    else:  # motocho
        content = render_motocho_pdf(db, fy, result)

    return _pdf_response(content, f"{form}_{result.year}.pdf")


@router.get("/{draft_id}/official-package")
def get_official_package(
    draft_id: uuid.UUID, db: Session = Depends(get_db)
) -> StreamingResponse:
    """Genera un ZIP con los documentos oficiales y archivos e-Tax.

    Replica el flujo de herramientas tipo freee/Yayoi: PDF oficiales para
    imprimir, datos e-Tax/CSV para importacion, libros auxiliares y un manifiesto
    JSON con la validacion estructural del .xtx.

    Args:
        draft_id: Id del `FilingDraft`.
        db: Sesion de BD.

    Returns:
        `StreamingResponse` con application/zip.
    """
    draft = _draft_or_404(db, draft_id)
    result, fy = _rebuild_for_draft(db, draft)
    _require_verified_export(result.year)
    include_xtx = False
    try:
        content = build_official_package(db, fy, result, include_xtx=include_xtx)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "official_package_file_missing", "message":
                    "必要なファイルがないため、申告書類一式を生成できません。", "details": {}},
        ) from exc
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/zip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": (
                f'attachment; filename="revision_kakutei_{result.year}.zip"'
            )
        },
    )


@router.get("/{draft_id}/xtx")
def get_xtx(draft_id: uuid.UUID, db: Session = Depends(get_db)) -> StreamingResponse:
    """Genera el archivo .xtx (XML) de la declaracion.

    Args:
        draft_id: Id del `FilingDraft`.
        db: Sesion de BD.

    Returns:
        `StreamingResponse` con el XML (application/xml).
    """
    draft = _draft_or_404(db, draft_id)
    result, _ = _rebuild_for_draft(db, draft)
    _require_verified_export(result.year)
    _require_xtx_xsd_verified()
    _require_complete_xtx(result)
    content = build_xtx(result)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/xml",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="shinkoku_{result.year}.xtx"'
        },
    )


@router.get("/{draft_id}/xtx/validation")
def get_xtx_validation(
    draft_id: uuid.UUID, db: Session = Depends(get_db)
) -> dict[str, object]:
    """Valida el .xtx generado contra el esquema confirmado KOA020 (令和7).

    Devuelve el reporte estructural (errores/avisos + cobertura de tags). NO es
    validacion XSD oficial (eso requiere el ``e-tax19.CAB`` del NTA); cubre
    estructura del sobre, tags confirmados (no inventar), formato de montos y
    redondeos legales. Util para que el frontend muestre "esquema OK" o avisos.

    Args:
        draft_id: Id del `FilingDraft`.
        db: Sesion de BD.

    Returns:
        El reporte como dict JSON-serializable.
    """
    draft = _draft_or_404(db, draft_id)
    result, _ = _rebuild_for_draft(db, draft)
    _require_verified_export(result.year)
    _require_xtx_xsd_verified()
    _require_complete_xtx(result)
    report = validate_xtx(build_xtx(result), year=result.year)
    return report.as_dict()


@router.get("/{draft_id}/csv")
def get_csv(draft_id: uuid.UUID, db: Session = Depends(get_db)) -> StreamingResponse:
    """Genera el CSV (SHIFT-JIS) del 決算書.

    Args:
        draft_id: Id del `FilingDraft`.
        db: Sesion de BD.

    Returns:
        `StreamingResponse` con el CSV (text/csv; charset=shift_jis).
    """
    draft = _draft_or_404(db, draft_id)
    result, _ = _rebuild_for_draft(db, draft)
    _require_verified_export(result.year)
    content = build_kessansho_csv(result)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=shift_jis",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="kessansho_{result.year}.csv"'
        },
    )
