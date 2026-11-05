"""Servicios de generacion de formularios del 確定申告 — Fase 3B-2.

Capas:
    - `drafting`: ensambla el `FilingDraft` (calculo completo desde la BD).
    - `kessansho`: 青色申告決算書 (PL + BS) / 収支内訳書 (白色).
    - `shinkokusho`: 確定申告書 第一表・第二表.
    - `chobo`: 帳簿 (仕訳帳 + 総勘定元帳).
    - `pdf`: render de cada formulario a PDF (fuente JP embebida).
    - `etax_export`: export .xtx (XML) + CSV (SHIFT-JIS).

Punto de entrada de alto nivel: `build_filing_draft` (drafting) + los
renderizadores `render_*` (pdf) + `build_xtx` / `build_kessansho_csv`
(etax_export).
"""

from app.services.forms.drafting import (
    FilingDraftResult,
    build_filing_draft,
    collect_ledgers,
)
from app.services.forms.etax_export import build_kessansho_csv, build_xtx

__all__ = [
    "FilingDraftResult",
    "build_filing_draft",
    "build_kessansho_csv",
    "build_xtx",
    "collect_ledgers",
]
