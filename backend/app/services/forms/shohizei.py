"""Informe PDF orientativo de 消費税; no es un formulario de declaración."""

from __future__ import annotations

import io
import logging

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from app.domain.tax.consumption import (
    ConsumptionMethodKey,
    ConsumptionOption,
    ConsumptionResult,
)
from app.services.forms.drafting import TaxpayerProfile
from app.services.forms.pdf import _ensure_font, _Page, _reiwa, _yen
from app.services.forms.tax_office import resolve_tax_office

logger = logging.getLogger(__name__)


def render_shohizei(
    result: ConsumptionResult,
    *,
    taxpayer_name: str,
    taxpayer_profile: TaxpayerProfile | None = None,
) -> bytes:
    """Genera un informe orientativo de 消費税 que no sirve para presentar.

    Args:
        result: Resultado del calculo del 消費税 (las 3 opciones + sugerencia).
        taxpayer_name: Nombre del contribuyente (para el subtitulo).
        taxpayer_profile: Perfil del 納税者 (encabezado 税務署 + 納税地), opcional.

    Returns:
        Bytes del PDF.
    """
    font = _ensure_font()
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4)
    c.setTitle("消費税の参考計算（提出用ではありません）")
    p = _Page(c, font)
    p.header(
        "消費税の参考計算（提出用ではありません）",
        f"{_reiwa(result.year)}　{taxpayer_name}",
    )

    _render_header_block(p, result, taxpayer_profile)
    _render_sales_block(p, result)
    _render_recommended_block(p, result)
    _render_comparison_block(p, result)

    p.gap(3)
    p.note("※ これは試算資料であり、税務署への申告書ではありません。")
    p.note("※ 各制度の適用要件、届出状況、基準期間の売上は未確認です。")
    p.note("※ 登録番号は形式のみ確認。登録・取引時の有効性・請求書内容は未確認です。")
    p.note("※ 税率不明の取引は10%と仮定する場合があります。実際の書類をご確認ください。")
    p.note("※ 税務代理ではありません。")

    c.save()
    return buf.getvalue()


def _render_header_block(
    p: _Page, result: ConsumptionResult, profile: TaxpayerProfile | None
) -> None:
    """Encabezado: 税務署 + 納税地 + 課税期間."""
    office = resolve_tax_office(profile.filing_office_key if profile else None)
    p.section("提出先・課税期間", note=_reiwa(result.year))
    p.c.setFont(p.font, 11)
    p.c.drawString(p.left + 2 * mm, p.y, f"　{office.header_label}　提出")
    p.y -= 7 * mm

    period = f"自 令和{result.year - 2018}年1月1日　至 令和{result.year - 2018}年12月31日"
    p.kv_line([("課税期間", period)])
    if profile:
        postal = f"〒{profile.postal_code}" if profile.postal_code else "〒—"
        address = profile.address or "—"
        p.kv_line([("納税地", f"{postal}　{address}")])
        p.kv_line([("氏名", profile.name)])

    method_label = {
        "honsoku": "本則課税",
        "kani": "簡易課税",
        "tokurei_2wari": "2割特例",
    }.get(result.method_setting or "", result.method_setting or "未設定")
    p.kv_line([("計算方法（設定）", method_label)])


def _render_sales_block(p: _Page, result: ConsumptionResult) -> None:
    """Bloque 課税標準額・売上税額 (区分経理 8% / 10%)."""
    sb = result.sales_breakdown
    p.section("課税標準額・売上税額", note="区分経理（8%／10%）")
    p.field_row("①", "課税売上（10%・税込）", _yen(sb.taxable_sales_10))
    p.field_row("②", "課税売上（軽減8%・税込）", _yen(sb.taxable_sales_8))
    p.field_row("③", "売上に係る消費税額（10%・国税分）", _yen(sb.national_tax_10))
    p.field_row("④", "売上に係る消費税額（8%・国税分）", _yen(sb.national_tax_8))
    p.field_row(
        "⑤", "売上に係る消費税額 合計（国税分）", _yen(sb.national_tax_total), strong=True
    )


def _render_recommended_block(p: _Page, result: ConsumptionResult) -> None:
    """Bloque del metodo RECOMENDADO (el de menor 納付税額)."""
    rec = _option_by_method(result, result.recommended)
    if rec is None:
        return
    p.section("納付税額（推奨：最も納付が少ない方法）", note=rec.label)
    p.field_row("⑤", "売上に係る消費税額（国税分）", _yen(rec.sales_tax))
    p.field_row("⑥", "控除対象仕入税額（国税分）", _yen(rec.purchase_tax_credit))
    p.field_row("⑦", "差引税額（国税分）", _yen(rec.national_tax), strong=True)
    p.field_row("⑧", "地方消費税額", _yen(rec.local_tax))
    p.field_row(
        "⑨", "消費税及び地方消費税の合計（納付税額）", _yen(rec.total_tax), strong=True
    )
    if rec.note:
        p.note(f"計算方法：{rec.label}（{rec.note}）")


def _render_comparison_block(p: _Page, result: ConsumptionResult) -> None:
    """Tabla comparativa de las 3 opciones (本則 / 簡易 / 特例)."""
    p.section("計算方法の比較（参考）")
    p.table_header([("計算方法", 0), ("仕入税額控除", 70), ("納付税額", 0)])
    for opt in (result.honsoku, result.kani, result.tokurei):
        if opt.eligibility_status == "unavailable":
            p.table_row([(f"{opt.label}（対象外）", 0), ("—", 70), ("—", 0)])
            continue
        if opt.method == ConsumptionMethodKey.KANI and result.business_category is None:
            p.table_row([(f"{opt.label}（事業区分未設定）", 0), ("—", 70), ("—", 0)])
            continue
        mark = "★ " if opt.method == result.recommended else ""
        p.table_row(
            [
                (f"{mark}{opt.label}（要件未確認）", 0),
                (_yen(opt.purchase_tax_credit), 70),
                (_yen(opt.total_tax), 0),
            ]
        )
    if result.recommended_saving > 0:
        saving = _yen(result.recommended_saving)
        p.note(f"推奨の方法を選ぶと、最も高い方法より {saving} 少なくなります。")


def _option_by_method(
    result: ConsumptionResult, method: ConsumptionMethodKey | None
) -> ConsumptionOption | None:
    """Devuelve la `ConsumptionOption` por su clave (o ``None``)."""
    if method is None:
        return None
    return {
        ConsumptionMethodKey.HONSOKU: result.honsoku,
        ConsumptionMethodKey.KANI: result.kani,
        ConsumptionMethodKey.TOKUREI: result.tokurei,
    }.get(method)
