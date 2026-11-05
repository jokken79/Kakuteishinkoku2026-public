"""Render de los formularios a PDF con fuente japonesa embebida — Fase 3B-3.

Usa **reportlab** con la fuente CID CJK ``HeiseiKakuGo-W5`` (incluida en
reportlab; no requiere ningun .ttf externo), de modo que los kanji renderizan en
cualquier entorno.

⚠️ Alcance honesto: estos PDF son una **réplica FIEL del layout oficial del NTA
令和7年分** — replican los BLOQUES, las CASILLAS NUMERADAS (㋐①⑬㉕㉚㉜… con su
símbolo/número oficial visible) y el encabezado 「○○税務署長」 con la jurisdicción
del owner (津島). NO son el formulario pre-impreso oficial del NTA (overlay sobre
el PDF/OCR del 様式 con coordenadas milimétricas) — para el envío real se usa el
.xtx + e-Taxソフト o el 作成コーナー. Esta réplica prioriza fidelidad estructural
+ numeración correcta + datos verificados.

Formularios:
    - shinkokusho:  確定申告書 第一表・第二表 (令和7 — réplica fiel)
    - kessansho:    青色申告決算書 (P1 損益計算書 + P4 貸借対照表) o 収支内訳書 (白色)
    - shiwakecho:   仕訳帳
    - motocho:      総勘定元帳
"""

from __future__ import annotations

import io
import logging
from collections.abc import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Account, FiscalYear, JournalEntry
from app.models.enums import FilingType
from app.services.forms.drafting import FilingDraftResult, collect_ledgers
from app.services.forms.tax_office import resolve_tax_office

logger = logging.getLogger(__name__)

# Fuente CJK embebida de reportlab (sin .ttf externo). Robusta para kanji.
_JP_FONT = "HeiseiKakuGo-W5"
_FONT_REGISTERED = False

# Paleta sumi (espejo discreto del design system del frontend).
_SUMI = colors.HexColor("#1b2030")
_SUMI_SOFT = colors.HexColor("#5a6175")
_HAIRLINE = colors.HexColor("#d8d4cc")
_SEIJI = colors.HexColor("#3e9b86")
_PAPER_SINK = colors.HexColor("#f3f0e9")
_BOX_BG = colors.HexColor("#eef4f2")  # fondo tenue de la casilla numerada.
_BOX_LINE = colors.HexColor("#9aa3a0")


def _ensure_font() -> str:
    """Registra (una vez) la fuente JP CID y devuelve su nombre.

    Returns:
        Nombre de la fuente japonesa registrada.
    """
    global _FONT_REGISTERED
    if not _FONT_REGISTERED:
        pdfmetrics.registerFont(UnicodeCIDFont(_JP_FONT))
        _FONT_REGISTERED = True
    return _JP_FONT


def _yen(amount: int | None) -> str:
    """Formatea un entero de yenes como ``¥1,234`` (negativo con −)."""
    if amount is None:
        return "—"
    sign = "−" if amount < 0 else ""
    return f"{sign}¥{abs(amount):,}"


# Marcadores oficiales que NO tienen glifo en la fuente CID (Adobe-Japan1/cp932):
# se dibujan como número arábigo en un círculo propio. Los compuestos (㋐, ㉑㉒,
# rangos ⑰〜⑳) usan una etiqueta corta. Sólo ①〜⑳ se renderizan con el glifo nativo.
_FALLBACK_MARKER: dict[str, str] = {
    "㋐": "ｱ",  # 事業（営業等）収入 — círculo katakana 'a'.
    "㋔": "ｴ",  # 給与収入 — círculo katakana 'e'.
    "㉑": "21",
    "㉒": "22",
    "㉑㉒": "21·22",
    "㉓": "23",
    "㉔": "24",
    "㉕": "25",
    "㉖": "26",
    "㉗": "27",
    "㉘": "28",
    "㉙": "29",
    "㉚": "30",
    "㉛": "31",
    "㉜": "32",
    "㉝": "33",
    "㉝〜㊶": "33-41",
    "㊸": "43",
    "㊹": "44",
    "㊺": "45",
    "㊻": "46",
    "㊾": "49",
    "㊿": "50",
    "⑰〜⑳": "17-20",
    "㉔〜㉚": "24-30",
    "52": "52",
    "53": "53",
}


def _marker_text(marker: str) -> tuple[str, bool]:
    """Resuelve el texto a dibujar para un marcador y si usa glifo nativo.

    Args:
        marker: Marcador oficial (㋐①⑬㉕…), posiblemente compuesto.

    Returns:
        Tupla ``(text, circled)``: ``circled=True`` si es un glifo redondo nativo
        de la fuente (①〜⑳) que se dibuja tal cual; ``False`` si es un fallback
        ASCII que va dentro de un círculo dibujado.
    """
    if marker in _FALLBACK_MARKER:
        return _FALLBACK_MARKER[marker], False
    # ①〜⑳ (U+2460–2473) sí existen en la fuente CID: glifo nativo.
    if len(marker) == 1 and 0x2460 <= ord(marker) <= 0x2473:
        return marker, True
    # Cualquier otro caso: intentar nativo, pero por seguridad tratar como texto.
    try:
        marker.encode("cp932")
        return marker, True
    except UnicodeEncodeError:
        return marker, False


class _Page:
    """Helper de layout vertical sobre un `Canvas` (cursor que baja).

    Mantiene un cursor `y` y ofrece primitivas (titulo, fila clave-valor,
    casilla numerada, seccion, linea) con paginado automatico.
    """

    def __init__(self, canvas: Canvas, font: str) -> None:
        """Inicializa el helper.

        Args:
            canvas: Canvas de reportlab.
            font: Fuente JP registrada.
        """
        self.c = canvas
        self.font = font
        self.width, self.height = A4
        self.left = 16 * mm
        self.right = self.width - 16 * mm
        self.y = self.height - 20 * mm

    def _space(self, needed: float) -> None:
        """Pagina si no quedan `needed` puntos de alto."""
        if self.y - needed < 18 * mm:
            self.c.showPage()
            self.y = self.height - 20 * mm

    def header(self, title: str, subtitle: str | None = None) -> None:
        """Dibuja el titulo principal del formulario."""
        self.c.setFillColor(_SUMI)
        self.c.setFont(self.font, 16)
        self.c.drawString(self.left, self.y, title)
        self.y -= 7 * mm
        if subtitle:
            self.c.setFillColor(_SUMI_SOFT)
            self.c.setFont(self.font, 9)
            self.c.drawString(self.left, self.y, subtitle)
            self.y -= 6 * mm
        self.c.setStrokeColor(_SEIJI)
        self.c.setLineWidth(1.2)
        self.c.line(self.left, self.y, self.right, self.y)
        self.y -= 7 * mm

    def section(self, label: str, *, note: str | None = None) -> None:
        """Encabezado de seccion (banda tenue)."""
        self._space(12 * mm)
        self.c.setFillColor(_PAPER_SINK)
        self.c.rect(self.left, self.y - 2 * mm, self.right - self.left, 7 * mm, fill=1, stroke=0)
        self.c.setFillColor(_SUMI)
        self.c.setFont(self.font, 11)
        self.c.drawString(self.left + 2 * mm, self.y, label)
        if note:
            self.c.setFillColor(_SUMI_SOFT)
            self.c.setFont(self.font, 7.5)
            self.c.drawRightString(self.right - 2 * mm, self.y, note)
        self.y -= 7.5 * mm

    def _draw_box_marker(self, marker: str, x: float) -> None:
        """Dibuja la casilla con su símbolo/número oficial (①⑬㉕…) en `x`.

        La fuente CID ``HeiseiKakuGo-W5`` (Adobe-Japan1 / cp932) SOLO contiene
        los círculos ①〜⑳. Los marcadores oficiales superiores (㉑+), los de
        katakana circular (㋐㋔) y los de la zona ㊸+ NO tienen glifo en esa
        fuente y saldrían como caja vacía. Para esos, sustituimos el texto por
        su número arábigo (``_FALLBACK_MARKER``) dibujado dentro de un círculo,
        replicando visualmente la casilla redonda oficial.
        """
        box_w = 7 * mm
        box_h = 5.2 * mm
        cx = x + box_w / 2
        cy = self.y + 1.2 * mm
        text, circled = _marker_text(marker)
        self.c.setFillColor(_BOX_BG)
        self.c.setStrokeColor(_BOX_LINE)
        self.c.setLineWidth(0.5)
        if circled:
            # Glifo nativo (①〜⑳): cajita con el símbolo redondo de la fuente.
            self.c.rect(x, self.y - 1.4 * mm, box_w, box_h, fill=1, stroke=1)
            self.c.setFillColor(_SUMI)
            self.c.setFont(self.font, 9)
            self.c.drawCentredString(cx, self.y + 0.1 * mm, text)
        else:
            # Fallback: número arábigo dentro de un círculo dibujado (réplica).
            self.c.rect(x, self.y - 1.4 * mm, box_w, box_h, fill=1, stroke=0)
            self.c.setStrokeColor(_BOX_LINE)
            self.c.setLineWidth(0.6)
            self.c.circle(cx, cy, 2.3 * mm, stroke=1, fill=0)
            self.c.setFillColor(_SUMI)
            size = 7.5 if len(text) <= 2 else 6
            self.c.setFont("Helvetica", size)
            self.c.drawCentredString(cx, cy - size * 0.33, text)

    def field_row(
        self,
        marker: str | None,
        label: str,
        value: str,
        *,
        strong: bool = False,
        indent: float = 0,
    ) -> None:
        """Fila con casilla numerada (izq) — etiqueta — valor (der).

        Args:
            marker: Símbolo/número oficial de la casilla (㋐①⑬…) o ``None``.
            label: Etiqueta del concepto.
            value: Valor (yenes formateado).
            strong: Resalta la fila (totales).
            indent: Sangría adicional (mm) para subitems.
        """
        self._space(8 * mm)
        x0 = self.left + indent * mm
        if marker is not None:
            self._draw_box_marker(marker, x0)
            label_x = x0 + 9 * mm
        else:
            label_x = x0 + 2 * mm
        self.c.setFont(self.font, 10.5 if strong else 9.5)
        self.c.setFillColor(_SUMI if strong else _SUMI_SOFT)
        self.c.drawString(label_x, self.y, label)
        self.c.setFillColor(_SUMI)
        self.c.setFont(self.font, 11.5 if strong else 10.5)
        self.c.drawRightString(self.right - 2 * mm, self.y, value)
        self.y -= 4.2 * mm
        self.c.setStrokeColor(_HAIRLINE)
        self.c.setLineWidth(0.6 if strong else 0.3)
        self.c.line(self.left + 2 * mm, self.y, self.right - 2 * mm, self.y)
        self.y -= 2.4 * mm

    def row(self, label: str, value: str, *, strong: bool = False, indent: float = 0) -> None:
        """Fila clave (izq) — valor (der) SIN casilla (subitems, totales libres)."""
        self.field_row(None, label, value, strong=strong, indent=indent)

    def kv_line(self, pairs: Sequence[tuple[str, str]]) -> None:
        """Línea de pares etiqueta:valor en horizontal (encabezado del 第一表)."""
        self._space(7 * mm)
        x = self.left + 2 * mm
        self.c.setFont(self.font, 9)
        for label, value in pairs:
            self.c.setFillColor(_SUMI_SOFT)
            self.c.drawString(x, self.y, label)
            x += pdfmetrics.stringWidth(label, self.font, 9) + 2 * mm
            self.c.setFillColor(_SUMI)
            self.c.drawString(x, self.y, value)
            x += pdfmetrics.stringWidth(value, self.font, 9) + 8 * mm
        self.y -= 4 * mm
        self.c.setStrokeColor(_HAIRLINE)
        self.c.setLineWidth(0.3)
        self.c.line(self.left + 2 * mm, self.y, self.right - 2 * mm, self.y)
        self.y -= 3 * mm

    def note(self, text: str) -> None:
        """Linea de nota tenue (disclaimers, totales aclaratorios)."""
        self._space(6 * mm)
        self.c.setFont(self.font, 8)
        self.c.setFillColor(_SUMI_SOFT)
        self.c.drawString(self.left + 2 * mm, self.y, text)
        self.y -= 5.5 * mm

    def gap(self, h: float = 4) -> None:
        """Espacio vertical (mm)."""
        self.y -= h * mm

    def table_header(self, cols: Sequence[tuple[str, float]]) -> None:
        """Cabecera de tabla. `cols` = [(label, x_offset_mm), ...] (ultimo=right)."""
        self._space(8 * mm)
        self.c.setFont(self.font, 9)
        self.c.setFillColor(_SUMI)
        for i, (label, x) in enumerate(cols):
            xx = self.left + x * mm
            if i == len(cols) - 1:
                self.c.drawRightString(self.right - 2 * mm, self.y, label)
            else:
                self.c.drawString(xx, self.y, label)
        self.y -= 2 * mm
        self.c.setStrokeColor(_SUMI)
        self.c.setLineWidth(0.6)
        self.c.line(self.left + 2 * mm, self.y, self.right - 2 * mm, self.y)
        self.y -= 5 * mm

    def table_row(self, cells: Sequence[tuple[str, float]], *, right_last: bool = True) -> None:
        """Fila de tabla. `cells` = [(text, x_offset_mm), ...]."""
        self._space(6 * mm)
        self.c.setFont(self.font, 9)
        self.c.setFillColor(_SUMI)
        for i, (text, x) in enumerate(cells):
            if right_last and i == len(cells) - 1:
                self.c.drawRightString(self.right - 2 * mm, self.y, text)
            else:
                self.c.drawString(self.left + x * mm, self.y, text)
        self.y -= 4 * mm
        self.c.setStrokeColor(_HAIRLINE)
        self.c.setLineWidth(0.3)
        self.c.line(self.left + 2 * mm, self.y, self.right - 2 * mm, self.y)
        self.y -= 2.5 * mm


def _start(title: str, subtitle: str) -> tuple[Canvas, io.BytesIO, _Page]:
    """Crea canvas + buffer + helper de pagina con el header dibujado.

    Args:
        title: Titulo del formulario.
        subtitle: Subtitulo (anio, contribuyente).

    Returns:
        Tupla ``(canvas, buffer, page)``.
    """
    font = _ensure_font()
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4)
    c.setTitle(title)
    page = _Page(c, font)
    page.header(title, subtitle)
    return c, buf, page


def _reiwa(year: int) -> str:
    """Devuelve la etiqueta 令和 del anio (令和7 = 2025)."""
    return f"令和{year - 2018}年分"


# --- 確定申告書 第一表・第二表 (令和7 — réplica fiel) -------------------------


def _render_header_block(p: _Page, draft: FilingDraftResult) -> None:
    """Dibuja el encabezado oficial del 第一表 (税務署長 + 納税地 del owner)."""
    office = resolve_tax_office(
        draft.taxpayer_profile.filing_office_key if draft.taxpayer_profile else None
    )
    prof = draft.taxpayer_profile

    p.section("提出先・納税者", note=_reiwa(draft.year))
    # 「○○税務署長」 — solo el NOMBRE de la oficina (no su dirección).
    p.c.setFont(p.font, 11)
    p.c.setFillColor(_SUMI)
    p.c.drawString(p.left + 2 * mm, p.y, f"　{office.header_label}　提出")
    p.c.setFont(p.font, 8)
    p.c.setFillColor(_SUMI_SOFT)
    p.c.drawRightString(p.right - 2 * mm, p.y, f"管轄：{office.jurisdiction}")
    p.y -= 7 * mm

    postal = f"〒{prof.postal_code}" if prof and prof.postal_code else "〒—"
    address = (prof.address if prof and prof.address else None) or "—"
    p.kv_line([("納税地", f"{postal}　{address}")])

    name = prof.name if prof else draft.taxpayer_name
    kana = prof.name_kana if prof and prof.name_kana else "—"
    p.kv_line([("フリガナ", kana), ("氏名", name)])

    pairs: list[tuple[str, str]] = []
    if prof and prof.my_number_masked:
        pairs.append(("個人番号", prof.my_number_masked))
    if prof and prof.birth_date_label:
        pairs.append(("生年月日", prof.birth_date_label))
    if prof and prof.occupation:
        pairs.append(("職業", prof.occupation))
    pairs.append(("申告区分", _filing_label(draft.filing_type)))
    p.kv_line(pairs)


def _filing_label(filing_type: str) -> str:
    """Etiqueta legible de la modalidad de declaración."""
    return {
        FilingType.AOIRO_65.value: "青色申告（65万円控除）",
        FilingType.AOIRO_55.value: "青色申告（55万円控除）",
        FilingType.AOIRO_10.value: "青色申告（10万円控除）",
        FilingType.SHIROIRO.value: "白色申告",
    }.get(filing_type, filing_type)


def _render_deductions_block(p: _Page, draft: FilingDraftResult) -> None:
    """Dibuja el bloque 所得控除 con la numeración 令和7 (㉕基礎控除, ㉚合計).

    Mapeo de `deduction_breakdown` → casilla oficial 令和7 (research 06 §1):
        ⑬ 社会保険料 ⑭ 小規模企業共済等(iDeCo) ⑮ 生命保険料 ⑯ 地震保険料
        ⑰〜⑳ 寡婦/ひとり親/勤労学生/障害者 (bucket `other`)
        ㉑㉒ 配偶者(特別) ㉓ 扶養 ㉔ 特定親族特別控除(NUEVO 令和7)
        ㉕ 基礎控除  ㉖ ⑬〜㉕の計  ㉘ 医療費  ㉙ 寄附金  ㉚ 合計.
    """
    db = draft.tax.deduction_breakdown
    p.section("所得から差し引かれる金額（所得控除）", note="令和7年分 様式")

    # ⑬〜㉕: las que entran al subtotal ㉖.
    p.field_row("⑬", "社会保険料控除", _yen(db.social_insurance))
    p.field_row("⑭", "小規模企業共済等掛金控除", _yen(db.ideco))
    p.field_row("⑮", "生命保険料控除", _yen(db.life_insurance))
    p.field_row("⑯", "地震保険料控除", _yen(db.earthquake_insurance))
    p.field_row("⑰〜⑳", "寡婦・ひとり親／勤労学生・障害者控除", _yen(db.other))
    p.field_row("㉑㉒", "配偶者（特別）控除", _yen(db.spouse))
    p.field_row("㉓", "扶養控除", _yen(db.dependents))
    p.field_row("㉔", "特定親族特別控除（令和7新設）", _yen(0))
    p.field_row("㉕", "基礎控除", _yen(db.kiso))

    # ㉖ = ⑬〜㉕の計 (todo menos 医療費/寄附金, que van en ㉘㉙).
    subtotal = (
        db.social_insurance
        + db.ideco
        + db.life_insurance
        + db.earthquake_insurance
        + db.other
        + db.spouse
        + db.dependents
        + db.kiso
    )
    p.field_row("㉖", "⑬から㉕までの計", _yen(subtotal), strong=True)

    # ㉘㉙: fuera del subtotal ㉖; ㉗ 雑損控除 no modelado (se omite la casilla vacía).
    p.field_row("㉘", "医療費控除", _yen(db.medical))
    p.field_row("㉙", "寄附金控除（ふるさと納税）", _yen(db.furusato))
    p.field_row(
        "㉚", "合計（㉖＋㉗＋㉘＋㉙）",
        _yen(draft.tax.total_income_deductions), strong=True,
    )


def render_shinkokusho(draft: FilingDraftResult) -> bytes:
    """Genera el PDF del 確定申告書 第一表・第二表 (令和7 — réplica fiel).

    Args:
        draft: Resultado del ensamblado del 確定申告.

    Returns:
        Bytes del PDF.
    """
    tax = draft.tax
    c, buf, p = _start(
        "確定申告書 第一表（令和7年分）",
        f"{_reiwa(draft.year)}　所得税及び復興特別所得税の確定申告書",
    )

    # === 第一表 ===
    _render_header_block(p, draft)

    # --- 収入金額等 (㋐〜) ---
    p.section("収入金額等")
    p.field_row("㋐", "事業（営業等）", _yen(draft.sales_revenue))
    for item in tax.income_breakdown:
        if item.kind == "kyuyo":
            p.field_row("㋔", "給与", _yen(item.amount))

    # --- 所得金額等 (①〜⑫) ---
    p.section("所得金額等")
    p.field_row("①", "事業（営業等）", _yen(draft.business_income), strong=True)
    for item in tax.income_breakdown:
        if item.kind == "kyuyo":
            p.field_row("⑥", "給与", _yen(item.amount))
        elif item.kind == "fudosan":
            p.field_row("③", "不動産", _yen(item.amount))
        elif item.kind == "haito":
            p.field_row("⑤", "配当", _yen(item.amount))
        elif item.kind == "zatsu":
            p.field_row("⑩", "雑（合計）", _yen(item.amount))
        elif item.kind == "ichiji":
            p.field_row("⑪", "総合譲渡・一時", _yen(item.amount))
    p.field_row("⑫", "合計（所得金額）", _yen(tax.total_income), strong=True)

    # --- 所得控除 (令和7) ---
    _render_deductions_block(p, draft)

    # --- 税金の計算 (㉛〜) ---
    p.section("税金の計算")
    p.field_row("㉛", "課税される所得金額（⑫−㉚）", _yen(tax.taxable_income), strong=True)
    p.field_row("㉜", "上の㉛に対する税額", _yen(tax.income_tax_base))
    if tax.tax_credits:
        p.field_row("㉝〜㊶", "税額控除（配当・住宅借入金等）", _yen(tax.tax_credits))
    p.field_row("㊹", "再差引所得税額（基準所得税額）", _yen(tax.income_tax_after_credits))
    p.field_row("㊺", "復興特別所得税額（㊹×2.1%）", _yen(tax.reconstruction_tax))
    p.field_row(
        "㊻", "所得税及び復興特別所得税の額（㊹＋㊺）", _yen(tax.total_tax), strong=True
    )
    p.field_row("㊾", "源泉徴収税額", _yen(tax.withholding_total))
    is_refund = tax.final_amount < 0
    p.field_row("㊿", "申告納税額（㊻−㊾）", _yen(tax.total_tax - tax.withholding_total))
    if is_refund:
        p.field_row(
            "53", "第3期分の税額（還付される税金）",
            _yen(abs(tax.final_amount)), strong=True,
        )
    else:
        p.field_row(
            "52", "第3期分の税額（納める税金）", _yen(tax.final_amount), strong=True
        )

    # === 第二表 ===
    c.showPage()
    p.y = p.height - 20 * mm
    p.header("確定申告書 第二表（令和7年分）", "所得の内訳・各種控除の内訳")

    p.section("所得の内訳（源泉徴収税額）")
    p.table_header([("所得の種類", 0), ("収入金額", 60), ("源泉徴収税額", 0)])
    p.table_row(
        [("事業（営業等）", 0), (_yen(draft.sales_revenue), 60), (_yen(tax.withholding_total), 0)]
    )
    p.row("源泉徴収税額の合計額（㊾へ）", _yen(tax.withholding_total), strong=True)

    db = tax.deduction_breakdown
    p.section("保険料控除等の内訳")
    p.field_row("⑬", "社会保険料控除", _yen(db.social_insurance))
    p.field_row("⑭", "小規模企業共済等掛金控除", _yen(db.ideco))
    p.field_row("⑮", "生命保険料控除", _yen(db.life_insurance))
    p.field_row("⑯", "地震保険料控除", _yen(db.earthquake_insurance))

    p.section("本人・配偶者・親族に関する事項")
    p.field_row("㉑㉒", "配偶者（特別）控除", _yen(db.spouse))
    p.field_row("㉓", "扶養控除", _yen(db.dependents))

    p.section("住民税・事業税に関する事項")
    p.field_row("㉙", "寄附金税額控除（ふるさと納税）", _yen(db.furusato))
    p.row("徴収方法", "自分で納付／特別徴収（給与天引き）")

    p.gap(3)
    p.note("※ 本書類は支援ツールによる計算結果です。提出前に必ずご確認ください。")
    p.note("※ レイアウトは令和7年分 公式様式の忠実な再現です。")
    p.note("　（公式印刷フォームそのものではありません）")
    p.note("※ 税務代理ではありません。")

    c.save()
    return buf.getvalue()


# --- 青色申告決算書 / 収支内訳書 (P1 損益計算書 + P4 貸借対照表) ----------------

# Mapeo de 経費 (勘定科目 → casilla numerada del 損益計算書, research 06 §3).
# Solo los que el motor contable puede emitir; el resto cae a "その他経費" sin nº.
_EXPENSE_BOX_BY_NAME: dict[str, str] = {
    "租税公課": "⑦",
    "荷造運賃": "⑧",
    "水道光熱費": "⑨",
    "旅費交通費": "⑩",
    "通信費": "⑪",
    "広告宣伝費": "⑫",
    "接待交際費": "⑬",
    "損害保険料": "⑭",
    "修繕費": "⑮",
    "消耗品費": "⑯",
    "減価償却費": "⑰",
    "福利厚生費": "⑱",
    "給料賃金": "⑲",
    "外注工賃": "⑳",
    "利子割引料": "㉑",
    "地代家賃": "㉒",
    "貸倒金": "㉓",
    "雑費": "㉛",
}


def _expense_box(account_name: str) -> str | None:
    """Devuelve la casilla del 経費 por nombre de cuenta (None si no mapeado)."""
    for key, box in _EXPENSE_BOX_BY_NAME.items():
        if key in account_name:
            return box
    return None


def render_kessansho(draft: FilingDraftResult) -> bytes:
    """Genera el 青色申告決算書 (P1 損益計算書 + P4 貸借対照表) o 収支内訳書 (白色).

    Args:
        draft: Resultado del ensamblado.

    Returns:
        Bytes del PDF.
    """
    is_shiroiro = draft.filing_type == FilingType.SHIROIRO.value
    title = "収支内訳書（令和7年分）" if is_shiroiro else "青色申告決算書（令和7年分・一般用）"
    c, buf, p = _start(title, f"{_reiwa(draft.year)}　{draft.taxpayer_name}")

    pl = draft.income_statement
    bs = draft.balance_sheet

    # --- P1 損益計算書 ---
    p.section("損益計算書（P1）", note="令和7年分 様式")
    p.field_row("①", "売上（収入）金額", _yen(pl.total_revenue), strong=True)
    p.field_row("⑤", "差引原価（売上原価）", _yen(0))

    p.gap(1)
    p.note("経費（科目別）")
    other_total = 0
    for line in pl.expenses:
        box = _expense_box(line.account_name)
        if box is None:
            other_total += line.amount
            continue
        p.field_row(box, line.account_name, _yen(line.amount), indent=2)
    if other_total:
        p.field_row("㉔〜㉚", "その他経費", _yen(other_total), indent=2)
    p.field_row("㉜", "経費計", _yen(pl.total_expense), strong=True)

    p.gap(1)
    p.field_row("㉝", "差引金額（①−⑤−㉜）", _yen(pl.net_income), strong=True)
    if not is_shiroiro:
        p.field_row("㊸", "青色申告特別控除前の所得金額", _yen(pl.net_income))
        p.field_row("㊹", "青色申告特別控除額", _yen(draft.aoiro_deduction))
        p.field_row("㊺", "所得金額（第一表①へ）", _yen(draft.business_income), strong=True)

    # --- P4 貸借対照表 — solo 青色 ---
    if not is_shiroiro:
        p.section("貸借対照表（P4・期末 12/31）")
        p.note("資産の部")
        for bsline in bs.assets:
            p.row(bsline.account_name, _yen(bsline.amount), indent=2)
        p.row("資産合計", _yen(bs.total_assets), strong=True)
        p.gap(1)
        p.note("負債・資本の部")
        for bsline in bs.liabilities:
            p.row(bsline.account_name, _yen(bsline.amount), indent=2)
        for bsline in bs.equity:
            p.row(bsline.account_name, _yen(bsline.amount), indent=2)
        p.row("青色申告特別控除前の所得金額", _yen(bs.net_income), indent=2)
        p.row(
            "負債・資本合計",
            _yen(bs.total_liabilities + bs.total_equity + bs.net_income),
            strong=True,
        )
        p.gap(1)
        balanced = "一致（資産 ＝ 負債＋資本＋所得）" if bs.is_balanced else "不一致（要確認）"
        p.note(f"貸借一致チェック：{balanced}　／　所得金額 BS＝PL：{_yen(bs.net_income)}")

    p.gap(3)
    p.note("※ 計算は確認済みの仕訳と売上から自動生成しています。提出前にご確認ください。")
    p.note("※ レイアウトは令和7年分 公式様式の忠実な再現です。")
    p.note("　（公式印刷フォームそのものではありません）")
    c.save()
    return buf.getvalue()


# --- 仕訳帳 ----------------------------------------------------------------


def render_shiwakecho(session: Session, fiscal_year: FiscalYear, draft: FilingDraftResult) -> bytes:
    """Genera el 仕訳帳 (libro diario) desde los asientos materializados.

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year: 年度.
        draft: Resultado del ensamblado (para el header).

    Returns:
        Bytes del PDF.
    """
    c, buf, p = _start(
        "仕訳帳", f"{_reiwa(draft.year)}　{draft.taxpayer_name}"
    )
    p.table_header(
        [("日付", 0), ("摘要", 22), ("借方科目", 78), ("貸方科目", 118), ("金額", 0)]
    )

    accounts = {a.id: a for a in session.scalars(select(Account)).all()}
    entries = list(
        session.scalars(
            select(JournalEntry)
            .where(JournalEntry.fiscal_year_id == fiscal_year.id)
            .order_by(JournalEntry.date, JournalEntry.id)
        ).all()
    )

    for entry in entries:
        debit_lines = [ln for ln in entry.lines if ln.side == "debit"]
        credit_lines = [ln for ln in entry.lines if ln.side == "credit"]
        rows = max(len(debit_lines), len(credit_lines))
        for i in range(rows):
            d = debit_lines[i] if i < len(debit_lines) else None
            cr = credit_lines[i] if i < len(credit_lines) else None
            d_name = accounts[d.account_id].name if d else ""
            c_name = accounts[cr.account_id].name if cr else ""
            amount = _yen(d.amount) if d else (_yen(cr.amount) if cr else "")
            p.table_row(
                [
                    (entry.date.isoformat() if i == 0 else "", 0),
                    ((entry.description or "")[:14] if i == 0 else "", 22),
                    (d_name, 78),
                    (c_name, 118),
                    (amount, 0),
                ]
            )

    p.gap(3)
    p.note(f"仕訳件数：{len(entries)}件　（確認済みの取引と売上から生成）")
    c.save()
    return buf.getvalue()


# --- 総勘定元帳 ------------------------------------------------------------


def render_motocho(session: Session, fiscal_year: FiscalYear, draft: FilingDraftResult) -> bytes:
    """Genera el 総勘定元帳 (mayor) por cuenta con saldo acumulado.

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year: 年度.
        draft: Resultado del ensamblado (para el header).

    Returns:
        Bytes del PDF.
    """
    c, buf, p = _start(
        "総勘定元帳", f"{_reiwa(draft.year)}　{draft.taxpayer_name}"
    )
    ledgers = collect_ledgers(session, fiscal_year)

    for ledger in ledgers:
        p.section(f"{ledger.account_code}　{ledger.account_name}")
        p.table_header(
            [("日付", 0), ("摘要", 26), ("借方", 80), ("貸方", 108), ("残高", 0)]
        )
        for mv in ledger.movements:
            p.table_row(
                [
                    (mv.date_iso, 0),
                    ((mv.description or "")[:16], 26),
                    (_yen(mv.debit) if mv.debit else "", 80),
                    (_yen(mv.credit) if mv.credit else "", 108),
                    (_yen(mv.balance), 0),
                ]
            )
        p.row("残高", _yen(ledger.balance), strong=True)
        p.gap(2)

    c.save()
    return buf.getvalue()
