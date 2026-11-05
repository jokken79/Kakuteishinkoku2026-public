"""Construccion del 仕訳 candidato a partir de una fila CSV de gasto.

Espejo de `app.services.ocr.pipeline._build_journal_candidate`, pero para una
transaccion de banco/tarjeta (sin desglose de 税 por linea): el CSV trae el
total 税込, asi que se descompone en base + 消費税 con la tasa por defecto (10%)
y se arma un asiento balanceado (借方 = gasto, 貸方 = 事業主借).

El 勘定科目 se sugiere reusando `classify_vendor` (mismo mapeo que OCR y seed).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from app.services.import_csv.parser import ParsedCsvRow
from app.services.ocr.classifier import AccountClassifier, get_default_classifier
from app.services.ocr.pipeline import (
    JournalEntryCandidate,
    JournalLineCandidate,
)

# Tasa de 消費税 por defecto para gastos de CSV (no hay desglose por linea).
_DEFAULT_TAX_RATE = 10
# Cuenta de contrapartida: 事業主借 (gasto pagado por el titular).
_OWNER_CREDIT_ACCOUNT = "312"


@dataclass
class CsvJournalProposal:
    """Propuesta completa para una fila de gasto del CSV.

    Args:
        account_code: 勘定科目 sugerido para el gasto.
        account_confidence: Confianza de la sugerencia (0.0-1.0).
        tax_lines: Desglose ``[{base, tax, rate}]`` del total 税込.
        journal: Asiento candidato balanceado (借方/貸方).
    """

    account_code: str
    account_confidence: float
    tax_lines: list[dict[str, Any]] = field(default_factory=list)
    journal: JournalEntryCandidate | None = None


def _tax_lines_from_total(total: int, rate: int = _DEFAULT_TAX_RATE) -> list[dict[str, Any]]:
    """Descompone un total 税込 en base + 消費税 para la tasa dada.

    Args:
        total: Importe total con impuesto incluido (yenes).
        rate: Tasa de consumo (8 o 10).

    Returns:
        Lista con una linea ``{base, tax, rate}`` (区分経理 por tasa).
    """
    base = round(total / (1 + rate / 100))
    tax = total - base
    return [{"base": base, "tax": tax, "rate": rate}]


def build_proposal(
    row: ParsedCsvRow,
    *,
    classifier: AccountClassifier | None = None,
    tax_rate: int = _DEFAULT_TAX_RATE,
) -> CsvJournalProposal:
    """Construye el 仕訳 candidato para una fila de gasto del CSV.

    Args:
        row: Fila parseada (debe ser importable: gasto con fecha+monto).
        classifier: Clasificador de 科目. Si es ``None`` usa el de reglas.
        tax_rate: Tasa de 消費税 a aplicar al total (default 10%).

    Returns:
        `CsvJournalProposal` con 科目 sugerido, tax_lines y asiento balanceado.
    """
    clf = classifier or get_default_classifier()
    suggestion = clf.suggest(row.vendor, row.vendor or "")
    total = row.amount or 0
    tax_lines = _tax_lines_from_total(total, tax_rate) if total else []

    lines: list[JournalLineCandidate] = [
        JournalLineCandidate(
            side="debit",
            account_code=suggestion.account_code,
            amount=total,
            tax_rate=tax_rate if total else None,
        ),
        JournalLineCandidate(
            side="credit", account_code=_OWNER_CREDIT_ACCOUNT, amount=total
        ),
    ]
    journal = JournalEntryCandidate(
        date=row.date,
        description=row.vendor or "CSV取込",
        lines=lines,
    )

    return CsvJournalProposal(
        account_code=suggestion.account_code,
        account_confidence=suggestion.confidence,
        tax_lines=tax_lines,
        journal=journal,
    )


def proposal_date(row: ParsedCsvRow) -> datetime.date | None:
    """Devuelve la fecha del asiento (la de la fila), util para el endpoint."""
    return row.date
