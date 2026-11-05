"""確定申告書 第一表・第二表 — Fase 3B-2.

Capa fina de dominio del 申告書: mapea los numeros del calculo fiscal (所得 del
PL, 所得控除 de las deducciones, 課税所得, 所得税, 復興税, 源泉/予定, 納付額/還付金)
a las secciones oficiales del 確定申告書 y los renderiza a PDF.

El calculo vive en `app.domain.tax` y se ensambla en `drafting`; aqui se proyecta
a la estructura del formulario (第一表 收入・所得・控除・税額 / 第二表 源泉・納付).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.forms.drafting import FilingDraftResult
from app.services.forms.pdf import render_shinkokusho


@dataclass
class ShinkokushoSummary:
    """Resumen estructurado del 確定申告書 (第一表・第二表).

    Args:
        sales_revenue: 事業（営業等）収入金額.
        business_income: 事業所得（青色申告特別控除後）.
        total_income: 合計所得金額.
        total_deductions: 所得控除の合計.
        taxable_income: 課税される所得金額.
        income_tax_base: 基準所得税額.
        reconstruction_tax: 復興特別所得税.
        total_tax: 所得税及び復興特別所得税の額.
        withholding_total: 源泉徴収・予定納税の合計.
        final_amount: 納付額 (>0) / 還付金 (<0).
        is_refund: ``True`` si hay 還付金.
    """

    sales_revenue: int
    business_income: int
    total_income: int
    total_deductions: int
    taxable_income: int
    income_tax_base: int
    reconstruction_tax: int
    total_tax: int
    withholding_total: int
    final_amount: int
    is_refund: bool


def summarize_shinkokusho(draft: FilingDraftResult) -> ShinkokushoSummary:
    """Proyecta el `FilingDraftResult` al resumen del 申告書.

    Args:
        draft: Resultado del ensamblado del 確定申告.

    Returns:
        `ShinkokushoSummary` con los campos del 第一表・第二表.
    """
    tax = draft.tax
    return ShinkokushoSummary(
        sales_revenue=draft.sales_revenue,
        business_income=draft.business_income,
        total_income=tax.total_income,
        total_deductions=tax.total_income_deductions,
        taxable_income=tax.taxable_income,
        income_tax_base=tax.income_tax_base,
        reconstruction_tax=tax.reconstruction_tax,
        total_tax=tax.total_tax,
        withholding_total=tax.withholding_total,
        final_amount=tax.final_amount,
        is_refund=tax.final_amount < 0,
    )


def render_shinkokusho_pdf(draft: FilingDraftResult) -> bytes:
    """Renderiza el 確定申告書 第一表・第二表 a PDF.

    Args:
        draft: Resultado del ensamblado.

    Returns:
        Bytes del PDF.
    """
    return render_shinkokusho(draft)
