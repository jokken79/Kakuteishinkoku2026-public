"""Render A4 profesional de 売上書類 con tipografía japonesa CID."""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

from app.models.enums import (
    SalesDocumentStatus,
    SalesDocumentType,
    SalesPriceMode,
    SalesTaxCategory,
)
from app.models.sales_documents import SalesDocument, SalesDocumentLine

_FONT = "HeiseiKakuGo-W5"
_FONT_REGISTERED = False
_SUMI = colors.HexColor("#17212b")
_SUMI_SOFT = colors.HexColor("#5f6873")
_SEIJI = colors.HexColor("#2d7d6d")
_SEIJI_DARK = colors.HexColor("#1f5f53")
_SEIJI_SOFT = colors.HexColor("#eaf3f0")
_PAPER = colors.HexColor("#fbfaf7")
_PAPER_WHITE = colors.HexColor("#fffefa")
_HAIRLINE = colors.HexColor("#d7d9d8")
_SHUIRO = colors.HexColor("#b24036")
_STAMP = colors.HexColor("#f5efe9")
_BRAND_ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "brand"
_LOGO_ASSETS: dict[str, Path] = {}

_TITLE = {
    SalesDocumentType.ESTIMATE: "御 見 積 書",
    SalesDocumentType.DELIVERY_NOTE: "納 品 書",
    SalesDocumentType.INVOICE: "請 求 書",
    SalesDocumentType.RECEIPT: "領 収 書",
    SalesDocumentType.PURCHASE_ORDER: "発 注 書",
    SalesDocumentType.ORDER_ACKNOWLEDGEMENT: "発 注 請 書",
    SalesDocumentType.CONSOLIDATED_INVOICE: "合 算 請 求 書",
    SalesDocumentType.CORRECTED_INVOICE: "修 正 請 求 書",
}

_TAX_LABEL = {
    SalesTaxCategory.STANDARD_10: "10%",
    SalesTaxCategory.REDUCED_8: "8%※",
    SalesTaxCategory.EXEMPT: "非課税",
    SalesTaxCategory.OUT_OF_SCOPE: "対象外",
}

_PAYABLE_TYPES = {
    SalesDocumentType.INVOICE,
    SalesDocumentType.CONSOLIDATED_INVOICE,
    SalesDocumentType.CORRECTED_INVOICE,
}


def _ensure_font() -> str:
    global _FONT_REGISTERED
    if not _FONT_REGISTERED:
        pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
        _FONT_REGISTERED = True
    return _FONT


def _text(value: object | None) -> str:
    return "" if value is None else str(value)


def _yen(value: int) -> str:
    return f"¥{value:,}"


def _quantity(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _issuer_name(issuer: dict[str, object]) -> str:
    return _text(issuer.get("trade_name")) or _text(issuer.get("legal_name")) or "事業者"


def _issuer_address_parts(issuer: dict[str, object]) -> list[str]:
    line1 = _text(issuer.get("address_line1")) or _text(issuer.get("address"))
    return [
        part
        for part in [
            _text(issuer.get("postal_code")),
            line1,
            _text(issuer.get("address_line2")),
        ]
        if part
    ]


def _issuer_contact_parts(issuer: dict[str, object]) -> list[str]:
    return [
        part
        for part in [
            f"TEL {_text(issuer.get('phone'))}" if issuer.get("phone") else "",
            f"FAX {_text(issuer.get('fax'))}" if issuer.get("fax") else "",
            _text(issuer.get("email")),
            _text(issuer.get("website_url")),
        ]
        if part
    ]


def _resolve_logo_path(logo_ref: object | None) -> Path | None:
    value = _text(logo_ref).strip()
    if not value:
        return None
    mapped = _LOGO_ASSETS.get(value)
    if mapped and mapped.exists():
        return mapped
    candidate = Path(value)
    if candidate.is_file():
        return candidate
    asset_candidate = _BRAND_ASSET_DIR / value.lstrip("/\\")
    if asset_candidate.is_file():
        return asset_candidate
    return None


def _draw_logo(
    c: Canvas,
    issuer: dict[str, object],
    *,
    box_right: float,
    box_top: float,
    max_width: float,
    max_height: float,
) -> bool:
    if not issuer.get("show_logo", False):
        return False
    path = _resolve_logo_path(issuer.get("logo_ref"))
    if path is None:
        return False
    try:
        image = ImageReader(str(path))
        image_width, image_height = image.getSize()
    except (OSError, ValueError):
        return False
    if image_width <= 0 or image_height <= 0:
        return False
    scale = min(max_width / image_width, max_height / image_height)
    width = image_width * scale
    height = image_height * scale
    x = box_right - width
    y = box_top - height
    c.drawImage(image, x, y, width=width, height=height, mask="auto")
    return True


def _draw_wrapped(
    c: Canvas,
    text: str,
    x: float,
    y: float,
    *,
    max_chars: int,
    line_height: float,
    max_lines: int,
    color: colors.Color = _SUMI_SOFT,
    size: int = 8,
) -> float:
    c.setFillColor(color)
    c.setFont(_FONT, size)
    lines: list[str] = []
    for raw in text.splitlines() or [text]:
        value = raw.strip()
        while value:
            lines.append(value[:max_chars])
            value = value[max_chars:]
    for line in lines[:max_lines]:
        c.drawString(x, y, line)
        y -= line_height
    return float(y)


def _draw_draft_watermark(c: Canvas, document: SalesDocument) -> None:
    if document.status != SalesDocumentStatus.DRAFT:
        return
    width, height = A4
    c.saveState()
    c.setFillColor(colors.Color(0.4, 0.4, 0.4, alpha=0.12))
    c.setFont(_FONT, 54)
    c.translate(width / 2, height / 2)
    c.rotate(30)
    c.drawCentredString(0, 0, "下 書 き")
    c.restoreState()


def _draw_seal(c: Canvas, x: float, y: float, issuer: dict[str, object]) -> None:
    if not issuer.get("show_seal", True):
        return
    text = (_text(issuer.get("seal_text")) or "領収")[:4]
    c.saveState()
    c.setStrokeColor(_SHUIRO)
    c.setFillColor(colors.Color(0.7, 0.1, 0.08, alpha=0.06))
    c.setLineWidth(1.2)
    c.circle(x, y, 11 * mm, stroke=1, fill=1)
    c.setFillColor(_SHUIRO)
    c.setFont(_FONT, 10)
    c.drawCentredString(x, y + 1.5 * mm, text)
    c.setFont(_FONT, 6)
    c.drawCentredString(x, y - 5 * mm, "電子印影")
    c.restoreState()


def _tax_groups(document: SalesDocument) -> dict[SalesTaxCategory, int]:
    return {
        category: sum(line.amount for line in document.lines if line.tax_category == category)
        for category in SalesTaxCategory
    }


def _tax_row_amount(document: SalesDocument, category: SalesTaxCategory, amount: int) -> int:
    if document.price_mode == SalesPriceMode.INCLUSIVE:
        return amount
    if category == SalesTaxCategory.REDUCED_8:
        return amount + document.tax_8
    if category == SalesTaxCategory.STANDARD_10:
        return amount + document.tax_10
    return amount


def _draw_header(c: Canvas, document: SalesDocument, page: int) -> float:
    width, height = A4
    left = 18 * mm
    right = width - 18 * mm
    issuer = document.issuer_snapshot or {}
    customer = document.customer_snapshot or {}

    c.setFillColor(_PAPER)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColor(_SEIJI)
    c.rect(0, height - 5 * mm, width, 5 * mm, fill=1, stroke=0)

    c.setFillColor(_SUMI)
    c.setFont(_FONT, 21)
    c.drawString(left, height - 26 * mm, _TITLE[document.document_type])
    c.setFillColor(_SUMI_SOFT)
    c.setFont(_FONT, 8)
    c.drawRightString(right, height - 17 * mm, f"No. {document.document_number or 'DRAFT'}")
    c.drawRightString(right, height - 23 * mm, f"発行日　{document.issue_date.isoformat()}")
    if document.due_date:
        c.drawRightString(right, height - 29 * mm, f"お支払期限　{document.due_date.isoformat()}")

    c.setFillColor(_SUMI)
    c.setFont(_FONT, 13)
    customer_name = _text(customer.get("name")) or "取引先未設定"
    honorific = _text(customer.get("honorific")) or "御中"
    c.drawString(left, height - 45 * mm, f"{customer_name}　{honorific}")
    c.setStrokeColor(_SUMI)
    c.setLineWidth(0.6)
    c.line(left, height - 48 * mm, 110 * mm, height - 48 * mm)
    customer_address = " ".join(
        part
        for part in [_text(customer.get("postal_code")), _text(customer.get("address"))]
        if part
    )
    if customer_address:
        _draw_wrapped(
            c,
            customer_address,
            left,
            height - 54 * mm,
            max_chars=42,
            line_height=4 * mm,
            max_lines=2,
        )

    issuer_y = height - 43 * mm
    if _draw_logo(
        c,
        issuer,
        box_right=right,
        box_top=height - 34 * mm,
        max_width=42 * mm,
        max_height=25 * mm,
    ):
        issuer_y = height - 65 * mm

    c.setFillColor(_SUMI)
    c.setFont(_FONT, 13)
    c.drawRightString(right, issuer_y, _issuer_name(issuer))
    c.setFont(_FONT, 8)
    c.setFillColor(_SUMI_SOFT)
    y = issuer_y - 6 * mm
    if issuer.get("show_representative") and issuer.get("representative_name"):
        c.drawRightString(right, y, f"代表　{issuer['representative_name']}")
        y -= 6 * mm
    if issuer.get("department_name") or issuer.get("contact_person_name"):
        contact = " ".join(
            part
            for part in [
                _text(issuer.get("department_name")),
                _text(issuer.get("contact_person_name")),
            ]
            if part
        )
        c.drawRightString(right, y, f"担当　{contact}")
        y -= 6 * mm
    for line in _issuer_address_parts(issuer)[:2]:
        c.drawRightString(right, y, line[:50])
        y -= 5 * mm
    contact_line = " / ".join(_issuer_contact_parts(issuer)[:2])
    if contact_line:
        c.drawRightString(right, y, contact_line[:58])
        y -= 5 * mm
    if document.is_qualified_invoice and issuer.get("registration_number"):
        c.setFillColor(_SEIJI)
        c.drawRightString(right, y, f"登録番号 {_text(issuer.get('registration_number'))}")

    _draw_draft_watermark(c, document)

    if page > 1:
        c.setFillColor(_SUMI_SOFT)
        c.setFont(_FONT, 8)
        c.drawRightString(right, height - 35 * mm, f"{page}ページ")
    return float(height - 82 * mm)


def _draw_table_header(c: Canvas, y: float) -> float:
    left = 18 * mm
    widths = [84 * mm, 18 * mm, 16 * mm, 28 * mm, 28 * mm]
    labels = ["品名・内容", "数量", "単位", "単価", "金額"]
    c.setFillColor(_SUMI)
    c.rect(left, y - 8 * mm, sum(widths), 8 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(_FONT, 8)
    x = left
    for label, width in zip(labels, widths, strict=True):
        c.drawCentredString(x + width / 2, y - 5.2 * mm, label)
        x += width
    return float(y - 8 * mm)


def _draw_line(c: Canvas, y: float, document_line: SalesDocumentLine) -> float:
    line = document_line
    left = 18 * mm
    widths = [84 * mm, 18 * mm, 16 * mm, 28 * mm, 28 * mm]
    values = [
        f"{line.description[:29]}  {_TAX_LABEL[line.tax_category]}",
        _quantity(line.quantity),
        line.unit,
        _yen(line.unit_price),
        _yen(line.amount),
    ]
    c.setStrokeColor(_HAIRLINE)
    c.setLineWidth(0.35)
    c.line(left, y - 9 * mm, left + sum(widths), y - 9 * mm)
    c.setFillColor(_SUMI)
    c.setFont(_FONT, 8)
    x = left
    for index, (value, width) in enumerate(zip(values, widths, strict=True)):
        if index == 0:
            c.drawString(x + 2 * mm, y - 5.8 * mm, value)
        else:
            c.drawRightString(x + width - 2 * mm, y - 5.8 * mm, value)
        x += width
    return float(y - 9 * mm)


def _draw_totals(c: Canvas, document: SalesDocument, y: float) -> float:
    right = A4[0] - 18 * mm
    label_x = right - 66 * mm
    rows = [
        ("小計", document.subtotal, False),
        ("消費税（8%）", document.tax_8, False),
        ("消費税（10%）", document.tax_10, False),
        ("合計金額", document.total, True),
    ]
    for label, amount, strong in rows:
        c.setFillColor(_SEIJI_SOFT if strong else _PAPER)
        c.rect(label_x, y - 9 * mm, 66 * mm, 9 * mm, fill=1, stroke=0)
        c.setFillColor(_SUMI)
        c.setFont(_FONT, 11 if strong else 8)
        c.drawString(label_x + 3 * mm, y - 6 * mm, label)
        c.drawRightString(right - 3 * mm, y - 6 * mm, _yen(amount))
        y -= 9 * mm
    return float(y)


def _draw_footer(c: Canvas, document: SalesDocument, y: float) -> None:
    left = 18 * mm
    issuer = document.issuer_snapshot or {}
    c.setFillColor(_SUMI)
    c.setFont(_FONT, 8)
    if document.subject:
        c.drawString(left, y - 5 * mm, f"件名　{document.subject[:50]}")
        y -= 8 * mm
    if document.notes:
        c.setFillColor(_SUMI_SOFT)
        c.drawString(left, y - 5 * mm, f"備考　{document.notes[:76]}")
        y -= 8 * mm
    if issuer.get("document_footer_note"):
        c.setFillColor(_SUMI_SOFT)
        y = _draw_wrapped(
            c,
            f"共通備考　{_text(issuer.get('document_footer_note'))}",
            left,
            y - 5 * mm,
            max_chars=74,
            line_height=4 * mm,
            max_lines=2,
        )
    bank = " ".join(
        part
        for part in [
            _text(issuer.get("bank_name")),
            _text(issuer.get("bank_branch")),
            _text(issuer.get("bank_account_type")),
            _text(issuer.get("bank_account_number")),
            _text(issuer.get("bank_account_holder")),
        ]
        if part
    )
    if bank and issuer.get("show_bank_details", True) and document.document_type in _PAYABLE_TYPES:
        c.setFillColor(_SUMI)
        c.drawString(left, y - 5 * mm, f"振込先　{bank[:74]}")
    c.setFillColor(_SUMI_SOFT)
    c.setFont(_FONT, 7)
    c.drawCentredString(A4[0] / 2, 10 * mm, "※ 軽減税率対象品目には「※」を表示しています。")


def _draw_receipt_customer(c: Canvas, document: SalesDocument, y: float) -> float:
    left = 21 * mm
    customer = document.customer_snapshot or {}
    name = _text(customer.get("name")) or "取引先未設定"
    honorific = _text(customer.get("honorific")) or "様"
    c.setFillColor(_SUMI)
    c.setFont(_FONT, 14)
    c.drawString(left, y, f"{name}　{honorific}")
    c.setStrokeColor(_SUMI)
    c.setLineWidth(0.55)
    c.line(left, y - 3 * mm, 122 * mm, y - 3 * mm)
    address = " ".join(
        part
        for part in [_text(customer.get("postal_code")), _text(customer.get("address"))]
        if part
    )
    if address:
        return _draw_wrapped(
            c,
            address,
            left,
            y - 9 * mm,
            max_chars=44,
            line_height=4 * mm,
            max_lines=2,
        )
    return float(y - 13 * mm)


def _draw_receipt_amount(c: Canvas, document: SalesDocument, y: float) -> float:
    left = 21 * mm
    width = 168 * mm
    c.setFillColor(_SEIJI_DARK)
    c.roundRect(left, y - 29 * mm, width, 29 * mm, 2.4 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(_FONT, 9)
    c.drawString(left + 7 * mm, y - 10 * mm, "領収金額")
    c.setFont(_FONT, 24)
    c.drawRightString(left + width - 7 * mm, y - 10 * mm, _yen(document.total))
    c.setFont(_FONT, 8)
    c.drawRightString(left + width - 7 * mm, y - 22 * mm, "消費税等を含む")
    return float(y - 39 * mm)


def _draw_receipt_issuer(c: Canvas, document: SalesDocument, y: float) -> float:
    issuer = document.issuer_snapshot or {}
    left = 21 * mm
    width = 168 * mm
    panel_y = y - 39 * mm
    c.setStrokeColor(_HAIRLINE)
    c.setFillColor(colors.white)
    c.roundRect(left, panel_y, width, 39 * mm, 2.2 * mm, fill=1, stroke=1)

    c.setFillColor(_SUMI)
    c.setFont(_FONT, 11)
    c.drawString(left + 6 * mm, y - 9 * mm, _issuer_name(issuer))
    c.setFillColor(_SUMI_SOFT)
    c.setFont(_FONT, 7)
    info_y = y - 15 * mm
    if issuer.get("show_representative") and issuer.get("representative_name"):
        c.drawString(left + 6 * mm, info_y, f"代表　{issuer['representative_name']}")
        info_y -= 4.5 * mm
    if issuer.get("department_name") or issuer.get("contact_person_name"):
        contact = " ".join(
            part
            for part in [
                _text(issuer.get("department_name")),
                _text(issuer.get("contact_person_name")),
            ]
            if part
        )
        c.drawString(left + 6 * mm, info_y, f"担当　{contact}")
        info_y -= 4.5 * mm
    for line in _issuer_address_parts(issuer)[:2]:
        c.drawString(left + 6 * mm, info_y, line[:48])
        info_y -= 4.5 * mm
    contacts = " / ".join(_issuer_contact_parts(issuer)[:3])
    if contacts:
        c.drawString(left + 6 * mm, info_y, contacts[:72])
        info_y -= 4.5 * mm
    if document.is_qualified_invoice and issuer.get("registration_number"):
        c.setFillColor(_SEIJI)
        c.drawString(left + 6 * mm, info_y, f"登録番号 {_text(issuer.get('registration_number'))}")

    _draw_logo(
        c,
        issuer,
        box_right=left + width - 43 * mm,
        box_top=y - 7 * mm,
        max_width=34 * mm,
        max_height=24 * mm,
    )
    _draw_seal(c, left + width - 27 * mm, y - 19 * mm, issuer)
    return float(panel_y - 9 * mm)


def _draw_stamp_box(c: Canvas, issuer: dict[str, object]) -> None:
    if not issuer.get("show_stamp_box", True):
        return
    x = A4[0] - 54 * mm
    y = A4[1] - 86 * mm
    c.setStrokeColor(_HAIRLINE)
    c.setFillColor(_STAMP)
    c.roundRect(x, y, 32 * mm, 25 * mm, 1.5 * mm, fill=1, stroke=1)
    c.setFillColor(_SUMI_SOFT)
    c.setFont(_FONT, 7)
    c.drawCentredString(x + 16 * mm, y + 15 * mm, "収入印紙")
    c.setFont(_FONT, 5)
    c.drawCentredString(x + 16 * mm, y + 8 * mm, "必要な場合に貼付")


def _draw_receipt_detail_table(c: Canvas, document: SalesDocument, y: float) -> float:
    left = 21 * mm
    widths = [92 * mm, 18 * mm, 24 * mm, 34 * mm]
    labels = ["取引内容", "数量", "税区分", "金額"]
    c.setFillColor(_SUMI)
    c.rect(left, y - 8 * mm, sum(widths), 8 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(_FONT, 8)
    x = left
    for label, width in zip(labels, widths, strict=True):
        c.drawCentredString(x + width / 2, y - 5.2 * mm, label)
        x += width
    y -= 8 * mm
    for line in document.lines[:8]:
        c.setStrokeColor(_HAIRLINE)
        c.line(left, y - 9 * mm, left + sum(widths), y - 9 * mm)
        c.setFillColor(_SUMI)
        c.setFont(_FONT, 8)
        values = [
            line.description[:34],
            f"{_quantity(line.quantity)} {line.unit}",
            _TAX_LABEL[line.tax_category],
            _yen(line.amount),
        ]
        x = left
        for index, (value, width) in enumerate(zip(values, widths, strict=True)):
            if index == 0:
                c.drawString(x + 2 * mm, y - 5.8 * mm, value)
            else:
                c.drawRightString(x + width - 2 * mm, y - 5.8 * mm, value)
            x += width
        y -= 9 * mm
    return float(y - 4 * mm)


def _draw_receipt_tax_summary(c: Canvas, document: SalesDocument, y: float) -> float:
    groups = _tax_groups(document)
    left = 103 * mm
    width = 86 * mm
    rows = [
        ("8%対象（税込）", SalesTaxCategory.REDUCED_8, document.tax_8),
        ("10%対象（税込）", SalesTaxCategory.STANDARD_10, document.tax_10),
        ("非課税・対象外", SalesTaxCategory.OUT_OF_SCOPE, 0),
    ]
    c.setFillColor(_SEIJI_SOFT)
    c.rect(left, y - 8 * mm, width, 8 * mm, fill=1, stroke=0)
    c.setFillColor(_SUMI)
    c.setFont(_FONT, 8)
    c.drawString(left + 3 * mm, y - 5.2 * mm, "税率別内訳")
    y -= 8 * mm
    for label, category, tax in rows:
        amount = groups[category]
        if category == SalesTaxCategory.OUT_OF_SCOPE:
            amount += groups[SalesTaxCategory.EXEMPT]
        if amount == 0 and tax == 0:
            continue
        c.setStrokeColor(_HAIRLINE)
        c.line(left, y - 7 * mm, left + width, y - 7 * mm)
        c.setFillColor(_SUMI_SOFT)
        c.setFont(_FONT, 7)
        c.drawString(left + 3 * mm, y - 4.5 * mm, label)
        c.drawRightString(
            left + width - 3 * mm,
            y - 4.5 * mm,
            f"{_yen(_tax_row_amount(document, category, amount))} / 消費税 {_yen(tax)}",
        )
        y -= 7 * mm
    return float(y)


def _render_receipt_document(c: Canvas, document: SalesDocument) -> None:
    width, height = A4
    left = 21 * mm
    right = width - 21 * mm
    issuer = document.issuer_snapshot or {}

    c.setFillColor(_PAPER)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColor(_PAPER_WHITE)
    c.roundRect(14 * mm, 13 * mm, width - 28 * mm, height - 26 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(_SEIJI)
    c.rect(14 * mm, height - 19 * mm, width - 28 * mm, 4 * mm, fill=1, stroke=0)

    c.setFillColor(_SUMI_SOFT)
    c.setFont(_FONT, 7)
    c.drawString(left, height - 31 * mm, "RECEIPT")
    c.drawRightString(right, height - 31 * mm, f"No. {document.document_number or 'DRAFT'}")
    c.setFillColor(_SUMI)
    c.setFont(_FONT, 25)
    c.drawString(left, height - 43 * mm, _TITLE[SalesDocumentType.RECEIPT])
    c.setFillColor(_SUMI_SOFT)
    c.setFont(_FONT, 8)
    c.drawRightString(right, height - 43 * mm, f"発行日　{document.issue_date.isoformat()}")

    _draw_stamp_box(c, issuer)
    y = _draw_receipt_customer(c, document, height - 62 * mm)
    y = _draw_receipt_amount(c, document, y - 3 * mm)

    c.setFillColor(_SUMI)
    c.setFont(_FONT, 8)
    proviso = document.subject or _text(issuer.get("receipt_proviso")) or "商品・サービス代"
    c.drawString(left, y, f"但し　{proviso[:66]}　として")
    y -= 7 * mm
    message = (
        document.notes
        or _text(issuer.get("receipt_message"))
        or "上記金額を正に領収いたしました。"
    )
    c.setFillColor(_SUMI_SOFT)
    c.drawString(left, y, message[:76])
    y -= 11 * mm

    y = _draw_receipt_issuer(c, document, y)
    y = _draw_receipt_detail_table(c, document, y)
    y = _draw_receipt_tax_summary(c, document, y)

    if issuer.get("document_footer_note"):
        _draw_wrapped(
            c,
            _text(issuer.get("document_footer_note")),
            left,
            max(y - 6 * mm, 28 * mm),
            max_chars=78,
            line_height=4 * mm,
            max_lines=2,
        )
    c.setFillColor(_SUMI_SOFT)
    c.setFont(_FONT, 7)
    c.drawCentredString(width / 2, 22 * mm, "※ 軽減税率対象品目には「※」を表示しています。")
    _draw_draft_watermark(c, document)


def _render_standard_document(c: Canvas, document: SalesDocument) -> None:
    page = 1
    y = _draw_header(c, document, page)
    y = _draw_table_header(c, y)

    for line in document.lines:
        if y < 55 * mm:
            c.showPage()
            page += 1
            y = _draw_header(c, document, page)
            y = _draw_table_header(c, y)
        y = _draw_line(c, y, line)

    if y < 85 * mm:
        c.showPage()
        page += 1
        y = _draw_header(c, document, page)
    y -= 5 * mm
    y = _draw_totals(c, document, y)
    _draw_footer(c, document, y - 3 * mm)


def render_sales_document(document: SalesDocument) -> bytes:
    """Genera el PDF actual del documento; el servicio decide si archivarlo."""
    _ensure_font()
    buffer = io.BytesIO()
    c = Canvas(buffer, pagesize=A4)
    c.setTitle(_TITLE[document.document_type].replace(" ", ""))
    if document.document_type == SalesDocumentType.RECEIPT:
        _render_receipt_document(c, document)
    else:
        _render_standard_document(c, document)
    c.save()
    return buffer.getvalue()
