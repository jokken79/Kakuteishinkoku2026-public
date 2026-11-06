"""Paquete oficial de 確定申告書類.

Construye una descarga unica al estilo freee/Yayoi: PDF oficiales del NTA,
libros auxiliares, e-Tax y un manifiesto de validacion. Los PDFs oficiales no se
redibujan: se generan superponiendo datos sobre las plantillas NTA versionadas.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.domain.tax.consumption import calculate_consumption_for_year
from app.models.entities import FiscalYear
from app.models.enums import FilingType
from app.services.forms.chobo import render_motocho_pdf, render_shiwakecho_pdf
from app.services.forms.drafting import FilingDraftResult
from app.services.forms.etax_export import build_kessansho_csv, build_xtx
from app.services.forms.etax_validator import validate_xtx
from app.services.forms.kessansho_official import render_kessansho_official
from app.services.forms.shinkokusho_official import render_shinkokusho_official
from app.services.forms.shohizei import render_shohizei
from app.services.forms.shushi_official import render_shushi_official

_JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class PackageFile:
    """Archivo incluido en el ZIP oficial."""

    name: str
    content: bytes
    media_type: str
    description: str


def _taxpayer_summary(result: FilingDraftResult, fy: FiscalYear) -> dict[str, object]:
    """Datos no sensibles del contribuyente para el manifiesto."""
    taxpayer = fy.taxpayer
    return {
        "name": result.taxpayer_name,
        "filing_type": result.filing_type,
        "filing_office_key": (
            result.taxpayer_profile.filing_office_key
            if result.taxpayer_profile is not None
            else None
        ),
        "is_taxable_consumption": (
            bool(getattr(taxpayer, "is_taxable_consumption", False))
            if taxpayer is not None
            else False
        ),
    }


def _base_files(
    session: Session, fy: FiscalYear, result: FilingDraftResult, *, include_xtx: bool,
) -> list[PackageFile]:
    """Genera los documentos siempre disponibles para 所得税."""
    is_aoiro = result.filing_type != FilingType.SHIROIRO.value
    statement_pdf = (
        render_kessansho_official(result)
        if is_aoiro
        else render_shushi_official(result)
    )
    statement_name = (
        "02_kessansho_official.pdf" if is_aoiro else "02_shushi_official.pdf"
    )
    statement_desc = (
        "所得税青色申告決算書（一般用）1〜4ページ。2・3ページは未記入" if is_aoiro
        else "収支内訳書（一般用）1・2ページ。2ページは未記入"
    )
    files = [
        PackageFile(
            "01_shinkokusho_official.pdf",
            render_shinkokusho_official(result),
            "application/pdf",
            "所得税及び復興特別所得税の申告書 第一表・第二表",
        ),
        PackageFile(statement_name, statement_pdf, "application/pdf", statement_desc),
        PackageFile(
            "03_shiwakecho.pdf",
            render_shiwakecho_pdf(session, fy, result),
            "application/pdf",
            "仕訳帳",
        ),
        PackageFile(
            "04_motocho.pdf",
            render_motocho_pdf(session, fy, result),
            "application/pdf",
            "総勘定元帳",
        ),
        PackageFile(
            f"06_kessansho_{result.year}.csv",
            build_kessansho_csv(result),
            "text/csv; charset=shift_jis",
            "青色申告決算書/収支内訳書 CSV（SHIFT-JIS）",
        ),
    ]
    if include_xtx:
        files.append(PackageFile(
            f"05_shinkoku_{result.year}.xtx", build_xtx(result), "application/xml",
            "e-Tax 申告データ（KOA020）",
        ))
    return files


def _consumption_file(
    session: Session, result: FilingDraftResult
) -> PackageFile | None:
    """Agrega 消費税申告書 si el contribuyente es 課税事業者."""
    try:
        consumption = calculate_consumption_for_year(session, result.year)
    except ValueError:
        return None
    if not consumption.is_taxable:
        return None
    return PackageFile(
        f"07_shohizei_{result.year}.pdf",
        render_shohizei(
            consumption,
            taxpayer_name=result.taxpayer_name,
            taxpayer_profile=result.taxpayer_profile,
        ),
        "application/pdf",
        "消費税の参考計算（提出用ではありません）",
    )


def _manifest(
    result: FilingDraftResult,
    fy: FiscalYear,
    files: list[PackageFile],
) -> bytes:
    """Manifiesto legible y verificable del paquete generado."""
    xtx = next((file.content for file in files if file.name.endswith(".xtx")), None)
    validation = validate_xtx(xtx, year=result.year).as_dict() if xtx is not None else None
    data = {
        "package": "official-tax-filing-r7",
        "generated_at": datetime.now(_JST).isoformat(),
        "year": result.year,
        "reiwa_year": result.year - 2018,
        "taxpayer": _taxpayer_summary(result, fy),
        "basis": {
            "templates": [
                {
                    "file": "r07_01.pdf",
                    "form_code": "FA2205",
                    "name": "申告書第一表・第二表",
                    "source": "国税庁 令和7年分様式",
                },
                {
                    "file": "r07_kessansho.pdf",
                    "form_code": "FA3001",
                    "name": "所得税青色申告決算書（一般用）",
                    "source": "国税庁 令和7年分様式",
                },
                {
                    "file": "r07_05.pdf",
                    "form_code": "FA7050",
                    "name": "収支内訳書（一般用）",
                    "source": "国税庁 令和7年分様式",
                },
            ],
            "etax": "XTX no disponible; CSV de referencia sin validar para e-Tax",
        },
        "checks": {
            "xtx_validation": validation,
            "xtx_included": xtx is not None,
            "balance_sheet_balanced": result.balance_sheet.is_balanced,
            "confirmed_transactions": result.confirmed_count,
            "pending_transactions": result.pending_count,
        },
        "files": [
            {
                "name": file.name,
                "media_type": file.media_type,
                "description": file.description,
                "bytes": len(file.content),
            }
            for file in files
        ],
        "notes": [
            "PDFは国税庁の公式様式に値を重ねて生成しています。",
            ("青色申告決算書の2・3ページは未記入です。必要事項を確認し、記入してください。"
             if result.filing_type != FilingType.SHIROIRO.value
             else "収支内訳書の2ページは未記入です。必要事項を確認し、記入してください。"),
            "XTXは本人情報・明細・提出内容の検証が完了するまで含まれません。",
            "提出前にe-Taxまたは税務署提出用として内容を必ず確認してください。",
            "マイナンバー等の最終確認・追記が必要な場合があります。",
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def build_official_package(
    session: Session, fy: FiscalYear, result: FilingDraftResult, *, include_xtx: bool = False,
) -> bytes:
    """申告書類一式をZIPで生成する。

    Args:
        session: DB sesion.
        fy: 年度.
        result: Draft recalculado del mismo 年度.

    Returns:
        Bytes del ZIP con PDFs oficiales, e-Tax/CSV, libros y manifiesto.
    """
    if include_xtx:
        raise ValueError("XTX no disponible: falta completar la revisión para presentar")
    files = _base_files(session, fy, result, include_xtx=include_xtx)
    notice = (
        "BORRADOR PARA REVISIÓN — NO SE ENVÍA AUTOMÁTICAMENTE\n"
        "Los PDF contienen campos sin completar; verifica cada documento.\n"
        "Las deducciones sin categoría definida no se asignan automáticamente a su casilla.\n"
        "NO INCLUYE XTX: validar el XSD oficial no acredita aptitud para presentar. "
        "Falta completar la revisión fiscal y de presentación. "
        "Completa la declaración con la herramienta oficial.\n"
    )
    files.insert(0, PackageFile("00_LEER_REVISION.txt", notice.encode("utf-8"),
                                "text/plain; charset=utf-8", "Aviso de revisión"))
    consumption = _consumption_file(session, result)
    if consumption is not None:
        files.append(consumption)
    files.insert(
        0,
        PackageFile(
            "00_manifest.json",
            _manifest(result, fy, files),
            "application/json",
            "生成内容と検証結果",
        ),
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.writestr(file.name, file.content)
    return output.getvalue()
