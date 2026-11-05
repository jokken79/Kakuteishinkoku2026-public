"""帳簿 (仕訳帳 + 総勘定元帳) — Fase 3B-2.

Capa fina de dominio de los 帳簿 obligatorios para 青色申告 65万/55万 (複式簿記):
expone el render del 仕訳帳 (libro diario) y el 総勘定元帳 (mayor) a PDF, ambos
derivados de los asientos materializados por `drafting` y reagrupados por el
motor contable (`app.domain.accounting`).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import FiscalYear
from app.services.forms.drafting import FilingDraftResult
from app.services.forms.pdf import render_motocho, render_shiwakecho


def render_shiwakecho_pdf(
    session: Session, fiscal_year: FiscalYear, draft: FilingDraftResult
) -> bytes:
    """Renderiza el 仕訳帳 (libro diario) a PDF.

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year: 年度.
        draft: Resultado del ensamblado (para el header).

    Returns:
        Bytes del PDF.
    """
    return render_shiwakecho(session, fiscal_year, draft)


def render_motocho_pdf(
    session: Session, fiscal_year: FiscalYear, draft: FilingDraftResult
) -> bytes:
    """Renderiza el 総勘定元帳 (mayor) a PDF.

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year: 年度.
        draft: Resultado del ensamblado (para el header).

    Returns:
        Bytes del PDF.
    """
    return render_motocho(session, fiscal_year, draft)
