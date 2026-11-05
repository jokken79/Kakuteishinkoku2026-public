"""Servicio de importacion de extractos CSV de banco/tarjeta (Fase 4-1).

Convierte el CSV de un banco o tarjeta de credito japones en transacciones
candidatas (取引) de tipo gasto, en estado ``pending``, con su 仕訳 propuesto y
勘定科目 sugerido. NUNCA auto-confirma: el usuario revisa en la bandeja de 仕訳,
igual que el flujo de OCR.
"""

from __future__ import annotations

from app.services.import_csv.parser import (
    ColumnMapping,
    CsvImportResult,
    ParsedCsvRow,
    detect_columns,
    parse_csv,
    row_dedup_hash,
    sniff_decode,
)

__all__ = [
    "ColumnMapping",
    "CsvImportResult",
    "ParsedCsvRow",
    "detect_columns",
    "parse_csv",
    "row_dedup_hash",
    "sniff_decode",
]
