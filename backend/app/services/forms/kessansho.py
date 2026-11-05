"""青色申告決算書 (損益計算書 + 貸借対照表) / 収支内訳書 — Fase 3B-2.

Capa fina de dominio del 決算書: expone el render del formulario a PDF y un
resumen estructurado (dataclass) por si otra capa necesita los datos del 決算書
sin renderizar. La modalidad (青色 con BS / 白色 收支内訳書) se decide por el
`filing_type` del `FilingDraftResult`.

El calculo real (PL/BS) vive en `app.domain.accounting` y se ensambla en
`app.services.forms.drafting`; aqui solo se proyecta a formato de salida.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import FilingType
from app.services.forms.drafting import FilingDraftResult
from app.services.forms.pdf import render_kessansho


@dataclass
class KessanshoSummary:
    """Resumen estructurado del 決算書 (sin renderizar).

    Args:
        is_shiroiro: ``True`` si es 収支内訳書 (白色, sin 貸借対照表).
        total_revenue: 売上(収入)金額.
        total_expense: 経費合計.
        net_income: 差引金額 (所得金額 antes del 青色特別控除).
        aoiro_deduction: 青色申告特別控除.
        business_income: 所得金額 (tras 青色特別控除).
        total_assets: 資産合計 (0 si 白色).
        bs_balanced: ``True`` si el 貸借対照表 cuadra.
    """

    is_shiroiro: bool
    total_revenue: int
    total_expense: int
    net_income: int
    aoiro_deduction: int
    business_income: int
    total_assets: int
    bs_balanced: bool


def summarize_kessansho(draft: FilingDraftResult) -> KessanshoSummary:
    """Proyecta el `FilingDraftResult` al resumen del 決算書.

    Args:
        draft: Resultado del ensamblado del 確定申告.

    Returns:
        `KessanshoSummary` con los totales del 決算書.
    """
    pl = draft.income_statement
    bs = draft.balance_sheet
    return KessanshoSummary(
        is_shiroiro=draft.filing_type == FilingType.SHIROIRO.value,
        total_revenue=pl.total_revenue,
        total_expense=pl.total_expense,
        net_income=pl.net_income,
        aoiro_deduction=draft.aoiro_deduction,
        business_income=draft.business_income,
        total_assets=bs.total_assets,
        bs_balanced=bs.is_balanced,
    )


def render_kessansho_pdf(draft: FilingDraftResult) -> bytes:
    """Renderiza el 決算書 (PL+BS) / 収支内訳書 a PDF.

    Args:
        draft: Resultado del ensamblado.

    Returns:
        Bytes del PDF.
    """
    return render_kessansho(draft)
