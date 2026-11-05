"""Parsers de dominio sobre el texto crudo del OCR.

Cada submodulo es logica PURA (sin I/O, sin dependencias externas) que extrae un
campo del recibo. `parse_receipt` los orquesta y produce un `ParsedReceipt`
con confianzas por campo.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from app.services.ocr.base import OcrRawResult
from app.services.ocr.parsers.amount import AmountInfo, parse_amount
from app.services.ocr.parsers.date import parse_date
from app.services.ocr.parsers.reg_number import (
    RegistrationNumber,
    parse_registration_number,
)
from app.services.ocr.parsers.tax_rate import TaxLine, parse_tax_lines
from app.services.ocr.parsers.vendor import parse_vendor

__all__ = [
    "AmountInfo",
    "ParsedReceipt",
    "RegistrationNumber",
    "TaxLine",
    "parse_amount",
    "parse_date",
    "parse_receipt",
    "parse_registration_number",
    "parse_tax_lines",
    "parse_vendor",
]


@dataclass
class ParsedReceipt:
    """Recibo japones ya parseado a campos de dominio.

    Args:
        date: Fecha del recibo (取引年月日), o ``None``.
        vendor: Nombre del 取引先/店名, o ``None``.
        total: Importe total 税込 (entero yenes), o ``None``.
        tax_lines: Lineas por tasa ``[{rate, base, tax}]``.
        registration_number: 登録番号 ``T``+13, o ``None``.
        is_qualified_invoice: ``True`` si hay 登録番号 con checksum valido.
        confidence: Confianza global del parseo (0.0-1.0).
        raw_text: Texto crudo original (para revision/auditoria).
        field_confidences: Confianza por campo (date/vendor/total/...).
    """

    date: datetime.date | None = None
    vendor: str | None = None
    total: int | None = None
    tax_lines: list[dict[str, Any]] = field(default_factory=list)
    registration_number: str | None = None
    is_qualified_invoice: bool = False
    confidence: float = 0.0
    raw_text: str = ""
    field_confidences: dict[str, float] = field(default_factory=dict)


def parse_receipt(raw: OcrRawResult) -> ParsedReceipt:
    """Parsea un `OcrRawResult` a un `ParsedReceipt`.

    Aplica los parsers de fecha, vendor, monto, tasas y 登録番号, calcula la
    confianza por campo (presente = confianza del OCR, ausente = 0) y una
    confianza global como promedio ponderado simple de los campos presentes.

    Args:
        raw: Resultado crudo del proveedor OCR.

    Returns:
        `ParsedReceipt` con los campos extraidos y sus confianzas.
    """
    text = raw.raw_text
    base_conf = raw.overall_confidence or 0.0

    date_value = parse_date(text)
    vendor = parse_vendor(text)
    amount: AmountInfo = parse_amount(text)
    # Pasar el total 税込 permite derivar la base en recibos de una sola tasa
    # que solo traen 合計（税込）+ 内消費税 (sin bloque 内N%対象).
    tax_lines = parse_tax_lines(text, total=amount.total)
    reg = parse_registration_number(text)

    tax_lines_dicts = [
        {"rate": tl.rate, "base": tl.base, "tax": tl.tax} for tl in tax_lines
    ]

    is_qualified = bool(reg and reg.is_valid_checksum)

    field_conf: dict[str, float] = {
        "date": base_conf if date_value else 0.0,
        "vendor": base_conf if vendor else 0.0,
        "total": base_conf if amount.total is not None else 0.0,
        "tax_lines": base_conf if tax_lines_dicts else 0.0,
        "registration_number": (
            base_conf if (reg and reg.is_valid_checksum) else (base_conf * 0.5 if reg else 0.0)
        ),
    }
    present = [v for v in field_conf.values() if v > 0]
    overall = sum(present) / len(field_conf) if present else 0.0

    return ParsedReceipt(
        date=date_value,
        vendor=vendor,
        total=amount.total,
        tax_lines=tax_lines_dicts,
        registration_number=reg.value if reg else None,
        is_qualified_invoice=is_qualified,
        confidence=round(overall, 4),
        raw_text=text,
        field_confidences=field_conf,
    )
