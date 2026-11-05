"""Parser de extractos CSV de banco/tarjeta japones -> filas candidatas.

Pipeline (espejo del de OCR, plan 04 §3, pero sin imagen):

    csv_bytes
      -> sniff_decode (UTF-8 / UTF-8-SIG / SHIFT-JIS / CP932)
      -> detect_columns (取引日 / 金額|出金|入金 / 摘要|利用店名) con fallback manual
      -> parse_csv: por fila -> ParsedCsvRow (fecha, vendor, monto, gasto?)
      -> filtra solo gastos (debitos) -> Transaction candidata + 仕訳 candidato

Reglas de seguridad (NUNCA auto-registrar):
- Solo se importan GASTOS (debitos). Ingresos (creditos) se descartan: el alcance
  de la fase es generar 仕訳 de gastos, no inventar ingresos.
- Cada fila valida nace ``pending``; el frontend la confirma (1 tap), igual que OCR.

Idempotencia:
- `row_dedup_hash` produce un hash estable por (fecha + monto + vendor) de modo que
  un re-import del mismo extracto no duplica transacciones.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import logging
from dataclasses import dataclass, field

from app.services.ocr.parsers.amount import _normalize_digits
from app.services.ocr.parsers.date import parse_date

logger = logging.getLogger(__name__)

# Encodings a probar, en orden. SHIFT-JIS/CP932 son los tipicos de bancos JP.
_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp932", "shift_jis", "euc_jp")

# Sinonimos de header por campo (case/espacios normalizados). El orden importa:
# para el monto, primero columnas de gasto explicito (出金/お支払い), luego genericas.
_DATE_HEADERS: tuple[str, ...] = (
    "取引日", "利用日", "ご利用日", "日付", "年月日", "取引年月日", "date",
    "transaction date", "利用年月日", "計上日",
)
_VENDOR_HEADERS: tuple[str, ...] = (
    "摘要", "利用店名", "ご利用先", "利用先", "ご利用店名・商品名", "内容",
    "取引内容", "店名", "利用内容", "ご利用内容", "description", "payee",
    "支払先", "ご利用先など",
)
# Columna de monto generica con signo (negativo = gasto, o segun banco).
_AMOUNT_HEADERS: tuple[str, ...] = (
    "金額", "利用金額", "ご利用金額", "取引金額", "amount", "決済金額",
)
# Columnas explicitas de salida (gasto) y entrada (ingreso).
_DEBIT_HEADERS: tuple[str, ...] = (
    "出金", "出金金額", "お支払金額", "お支払い金額", "支払金額", "引き出し",
    "お引出し", "出金額", "withdrawal", "payment",
)
_CREDIT_HEADERS: tuple[str, ...] = (
    "入金", "入金金額", "お預り金額", "預入金額", "預り金額", "お預け入れ",
    "入金額", "deposit",
)


@dataclass
class ColumnMapping:
    """Mapeo de columnas del CSV a los campos del dominio.

    Los valores son indices de columna (0-based) en la fila del CSV. ``None``
    significa que la columna no esta presente.

    Args:
        date: Indice de la columna de fecha (取引日).
        vendor: Indice de la columna de 摘要/利用店名.
        amount: Indice de una columna de monto generica con signo.
        debit: Indice de la columna de salida/出金 (gasto).
        credit: Indice de la columna de entrada/入金 (ingreso).
    """

    date: int | None = None
    vendor: int | None = None
    amount: int | None = None
    debit: int | None = None
    credit: int | None = None

    @property
    def is_usable(self) -> bool:
        """``True`` si hay al menos fecha y alguna columna de monto."""
        has_amount = (
            self.amount is not None or self.debit is not None or self.credit is not None
        )
        return self.date is not None and has_amount


@dataclass
class ParsedCsvRow:
    """Una fila del CSV ya interpretada como candidata.

    Args:
        index: Numero de fila en el archivo (1-based, sin contar el header).
        date: Fecha del movimiento, o ``None`` si no se pudo parsear.
        vendor: 取引先/摘要 (puede ser ``None``).
        amount: Importe absoluto del movimiento (entero yenes), o ``None``.
        is_expense: ``True`` si es un gasto (debito), ``False`` si es ingreso.
        dedup_hash: Hash estable de la fila para idempotencia.
        skipped_reason: Motivo por el que la fila no es importable, o ``None``.
        raw: Celdas crudas de la fila (para debug/preview).
    """

    index: int
    date: datetime.date | None
    vendor: str | None
    amount: int | None
    is_expense: bool
    dedup_hash: str
    skipped_reason: str | None = None
    raw: list[str] = field(default_factory=list)

    @property
    def is_importable(self) -> bool:
        """``True`` si la fila es un gasto valido con fecha y monto."""
        return (
            self.skipped_reason is None
            and self.is_expense
            and self.date is not None
            and self.amount is not None
            and self.amount > 0
        )


@dataclass
class CsvImportResult:
    """Resultado del parseo completo de un CSV.

    Args:
        rows: Todas las filas parseadas (importables y no).
        mapping: Mapeo de columnas usado.
        encoding: Encoding detectado.
        headers: Cabeceras detectadas del CSV.
    """

    rows: list[ParsedCsvRow]
    mapping: ColumnMapping
    encoding: str
    headers: list[str]

    @property
    def importable(self) -> list[ParsedCsvRow]:
        """Subconjunto de filas importables (gastos validos)."""
        return [r for r in self.rows if r.is_importable]


def sniff_decode(data: bytes) -> tuple[str, str]:
    """Decodifica los bytes del CSV probando encodings japoneses comunes.

    Prueba en orden ``utf-8-sig``, ``utf-8``, ``cp932``, ``shift_jis``,
    ``euc_jp`` y devuelve el primero que decodifique sin error. CP932 es un
    superset de SHIFT-JIS (cubre los caracteres extendidos de Windows).

    Args:
        data: Bytes crudos del archivo CSV.

    Returns:
        Tupla ``(texto_decodificado, nombre_encoding)``.

    Raises:
        UnicodeDecodeError: Si ningun encoding de la lista logra decodificar.
    """
    last_error: UnicodeDecodeError | None = None
    for enc in _ENCODINGS:
        try:
            text = data.decode(enc)
            logger.debug("CSV decodificado con %s", enc)
            return text, enc
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    # Ultimo recurso: latin-1 nunca falla, pero degrada los kanji. Solo si todo
    # lo demas fallo (CSV corrupto), para no romper el flujo.
    if last_error is not None:
        logger.warning("CSV no decodificable con encodings JP; usando latin-1.")
        return data.decode("latin-1"), "latin-1"
    return data.decode("utf-8"), "utf-8"


def _normalize_header(header: str) -> str:
    """Normaliza un header para comparar (minusculas, sin espacios ni BOM)."""
    return header.strip().lstrip("﻿").replace(" ", "").replace("　", "").lower()


def _match_header(header: str, candidates: tuple[str, ...]) -> bool:
    """``True`` si el header normalizado contiene algun candidato normalizado."""
    norm = _normalize_header(header)
    return any(_normalize_header(c) in norm for c in candidates)


def detect_columns(headers: list[str]) -> ColumnMapping:
    """Detecta el mapeo de columnas a partir de las cabeceras del CSV.

    Empareja cada header con los sinonimos conocidos de fecha, vendor, monto,
    salida (出金) y entrada (入金). Es tolerante a espacios, full-width y BOM.

    Args:
        headers: Lista de cabeceras (primera fila del CSV).

    Returns:
        `ColumnMapping` con los indices detectados (``None`` los ausentes).
    """
    mapping = ColumnMapping()
    for i, header in enumerate(headers):
        if mapping.date is None and _match_header(header, _DATE_HEADERS):
            mapping.date = i
        elif mapping.debit is None and _match_header(header, _DEBIT_HEADERS):
            mapping.debit = i
        elif mapping.credit is None and _match_header(header, _CREDIT_HEADERS):
            mapping.credit = i
        elif mapping.amount is None and _match_header(header, _AMOUNT_HEADERS):
            mapping.amount = i
        elif mapping.vendor is None and _match_header(header, _VENDOR_HEADERS):
            mapping.vendor = i
    return mapping


def _parse_money(cell: str) -> int | None:
    """Parsea una celda de monto a entero con signo (yenes).

    Limpia ``¥``/``円``/comas/espacios, soporta digitos full-width y parentesis
    contables ``(1,200)`` como negativo. Devuelve ``None`` si la celda esta
    vacia o no es numerica.

    Args:
        cell: Texto de la celda de monto.

    Returns:
        Entero con signo (negativo = salida segun convencion del banco), o
        ``None`` si no hay numero.
    """
    text = cell.strip()
    if not text:
        return None
    negative = False
    # Parentesis contables: (1,200) = -1200.
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    # Signo explicito (menos ASCII o full-width "−"/"▲"/"-").
    if text[:1] in ("-", "−", "▲", "△"):
        negative = True
        text = text[1:]
    # Quitar simbolos de moneda.
    for sym in ("¥", "￥", "円", "\\", " ", "　"):
        text = text.replace(sym, "")
    digits = _normalize_digits(text)
    if not digits or not digits.lstrip("-").isdigit():
        return None
    value = int(digits)
    return -value if negative else value


def row_dedup_hash(
    date: datetime.date | None, amount: int | None, vendor: str | None
) -> str:
    """Hash estable de una fila para idempotencia (re-import no duplica).

    Usa (fecha ISO + monto absoluto + vendor normalizado). Dos filas con la misma
    fecha, monto y vendor se consideran el mismo movimiento.

    Args:
        date: Fecha del movimiento.
        amount: Importe (se usa el valor absoluto).
        vendor: 取引先/摘要.

    Returns:
        Hash hex (sha256) de la fila.
    """
    date_part = date.isoformat() if date else ""
    amount_part = str(abs(amount)) if amount is not None else ""
    vendor_part = (vendor or "").strip().lower()
    payload = f"{date_part}|{amount_part}|{vendor_part}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_amount(
    cells: list[str], mapping: ColumnMapping
) -> tuple[int | None, bool]:
    """Resuelve el monto y si es gasto a partir de las columnas mapeadas.

    Prioridad:
    1. Columnas explicitas 出金/入金 (debit/credit): 出金>0 => gasto.
    2. Columna generica con signo: negativo => gasto (convencion comun de banco).

    Args:
        cells: Celdas de la fila.
        mapping: Mapeo de columnas.

    Returns:
        Tupla ``(monto_absoluto | None, is_expense)``. Si no hay monto,
        ``(None, False)``.
    """

    def cell(i: int | None) -> str:
        if i is None or i >= len(cells):
            return ""
        return cells[i]

    # 1. Columnas explicitas de salida/entrada.
    if mapping.debit is not None or mapping.credit is not None:
        debit = _parse_money(cell(mapping.debit))
        credit = _parse_money(cell(mapping.credit))
        if debit:
            return abs(debit), True
        if credit:
            return abs(credit), False
        return None, False

    # 2. Columna generica con signo.
    if mapping.amount is not None:
        value = _parse_money(cell(mapping.amount))
        if value is None:
            return None, False
        # Negativo => gasto (convencion mayoritaria de extractos JP).
        is_expense = value < 0
        return abs(value), is_expense

    return None, False


def parse_csv(
    data: bytes,
    *,
    mapping: ColumnMapping | None = None,
    today: datetime.date | None = None,
) -> CsvImportResult:
    """Parsea un CSV de banco/tarjeta a filas candidatas.

    Detecta encoding y (si no se pasa ``mapping``) las columnas por header.
    Cada fila se interpreta como gasto/ingreso; solo los gastos validos quedan
    importables. NO persiste nada.

    Args:
        data: Bytes crudos del archivo CSV.
        mapping: Mapeo de columnas manual (override de la auto-deteccion).
        today: Fecha de referencia para el filtro de fechas futuras.

    Returns:
        `CsvImportResult` con todas las filas, el mapeo y el encoding usados.
    """
    text, encoding = sniff_decode(data)
    reader = csv.reader(io.StringIO(text))
    all_rows = [row for row in reader if any(c.strip() for c in row)]

    if not all_rows:
        return CsvImportResult(rows=[], mapping=ColumnMapping(), encoding=encoding, headers=[])

    headers = [c.strip() for c in all_rows[0]]
    detected = mapping or detect_columns(headers)

    # Si el mapeo no es usable (no hay fecha/monto), devolver sin filas (el
    # endpoint avisara para que el usuario re-mapee manualmente).
    if not detected.is_usable:
        logger.info("Mapeo de columnas no usable: %s", detected)
        return CsvImportResult(
            rows=[], mapping=detected, encoding=encoding, headers=headers
        )

    parsed_rows: list[ParsedCsvRow] = []
    for i, cells in enumerate(all_rows[1:], start=1):
        parsed_rows.append(_parse_row(i, cells, detected, today=today))

    return CsvImportResult(
        rows=parsed_rows, mapping=detected, encoding=encoding, headers=headers
    )


def _parse_row(
    index: int,
    cells: list[str],
    mapping: ColumnMapping,
    *,
    today: datetime.date | None,
) -> ParsedCsvRow:
    """Interpreta una fila de datos del CSV.

    Args:
        index: Numero de fila (1-based, sin header).
        cells: Celdas crudas de la fila.
        mapping: Mapeo de columnas.
        today: Fecha de referencia para el filtro de futuro.

    Returns:
        `ParsedCsvRow` con fecha, vendor, monto, naturaleza y motivo de skip.
    """

    def cell(i: int | None) -> str:
        if i is None or i >= len(cells):
            return ""
        return cells[i]

    raw_date = cell(mapping.date)
    date = parse_date(raw_date, today=today) if raw_date else None

    vendor_raw = cell(mapping.vendor).strip()
    vendor = vendor_raw or None

    amount, is_expense = _resolve_amount(cells, mapping)
    dedup = row_dedup_hash(date, amount, vendor)

    skipped: str | None = None
    if amount is None:
        skipped = "monto no detectado"
    elif date is None:
        skipped = "fecha no detectada"
    elif not is_expense:
        skipped = "ingreso (入金) — fuera de alcance"

    return ParsedCsvRow(
        index=index,
        date=date,
        vendor=vendor,
        amount=amount,
        is_expense=is_expense,
        dedup_hash=dedup,
        skipped_reason=skipped,
        raw=list(cells),
    )
