"""Extracción de montos clave de un PDF de 確定申告 de un año anterior.

Estrategia (research §sobre OCR del archivo histórico):

1. Extraer el TEXTO del PDF con `pymupdf` (fitz) — los 申告書 generados por
   software (e-Tax, freee, やよい, マネーフォワード) llevan texto seleccionable,
   así que no hace falta OCR de imagen para el caso común.
2. Sobre ese texto, aplicar regex tolerantes a los campos clave:
   所得金額 / 納付税額 / 還付金額 / 年度 (令和N年分) / 税務署.
3. Si un campo no se detecta con confianza, queda en ``None`` y el usuario lo
   completa a mano en la UI. **Nunca se inventan montos.**

Degradación con gracia: si `pymupdf` no está instalado o el PDF no trae texto
(es un escaneo de imagen), `extract_text_from_pdf` devuelve ``""`` y todos los
campos quedan ``None`` (el registro se crea igual, solo sin datos extraídos).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExtractedFiling:
    """Montos clave extraídos de un PDF de 確定申告 viejo.

    Todos los campos son opcionales: ``None`` significa "no se pudo extraer con
    confianza" (el usuario lo completa a mano). ``raw_text`` guarda el texto
    crudo del PDF para auditar/re-parsear.

    Args:
        year: 年度 gregoriano detectado (ej. 2024 == 令和6年分), o ``None``.
        total_income: 所得金額 (yenes), o ``None``.
        tax_paid: 納付税額 (yenes), o ``None``.
        tax_refund: 還付金額 (yenes), o ``None``.
        tax_office: Nombre del 税務署 detectado, o ``None``.
        raw_text: Texto crudo extraído del PDF (``""`` si no se pudo).
    """

    year: int | None = None
    total_income: int | None = None
    tax_paid: int | None = None
    tax_refund: int | None = None
    tax_office: str | None = None
    raw_text: str = ""

    @property
    def any_amount_extracted(self) -> bool:
        """``True`` si se extrajo al menos un monto clave."""
        return any(
            v is not None
            for v in (self.total_income, self.tax_paid, self.tax_refund)
        )


# --- Extracción de texto ---------------------------------------------------


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrae el texto seleccionable de un PDF con `pymupdf` (fitz).

    Import lazy: si `pymupdf` no está instalado, degrada con gracia devolviendo
    ``""`` (el registro se crea sin datos extraídos). No lanza por PDFs sin
    texto (escaneos): simplemente devuelve lo que haya.

    Args:
        pdf_bytes: Bytes del PDF subido.

    Returns:
        Texto concatenado de todas las páginas, o ``""`` si no se pudo extraer.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        logger.warning("pymupdf no instalado: no se extrae texto del PDF histórico.")
        return ""

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception as exc:  # noqa: BLE001 — degradar con gracia ante PDF corrupto.
        logger.warning("No se pudo extraer texto del PDF histórico: %s", exc)
        return ""


# --- Parsing de los montos -------------------------------------------------

# Un monto japonés: dígitos con separadores de miles opcionales (1,234,567) o
# con espacios entre grupos. Capturamos solo el número.
_AMOUNT = r"([0-9][0-9,\s]{0,15}[0-9]|[0-9])"

# 令和N年分 / 令和N年 — el año del 申告書 (and 平成 por compatibilidad).
_REIWA_RE = re.compile(r"令和\s*([0-9元]{1,2})\s*年")
_HEISEI_RE = re.compile(r"平成\s*([0-9元]{1,2})\s*年")
# 税務署 (ej. "津島税務署", "名古屋中税務署").
_TAX_OFFICE_RE = re.compile(r"([一-龥ぁ-んァ-ヶA-Za-z]{1,12}?税務署)")

# 所得金額（合計） / 所得金額等の合計 / 所得金額 — el 所得 total.
_INCOME_RES = [
    re.compile(r"所得金額(?:等)?(?:の合計|（合計）|\(合計\))?\D{0,12}?" + _AMOUNT),
    re.compile(r"合計所得金額\D{0,12}?" + _AMOUNT),
]
# 納める税金 / 申告納税額 / 納付税額 / 第3期分の税額（納める税金）.
_TAX_PAID_RES = [
    re.compile(r"納める税金\D{0,12}?" + _AMOUNT),
    re.compile(r"申告納税額\D{0,12}?" + _AMOUNT),
    re.compile(r"納付(?:する)?税額\D{0,12}?" + _AMOUNT),
]
# 還付される税金 / 還付金額 / 還付される金額.
_TAX_REFUND_RES = [
    re.compile(r"還付される(?:税金|金額)\D{0,12}?" + _AMOUNT),
    re.compile(r"還付金額\D{0,12}?" + _AMOUNT),
]


def _to_int(raw: str | None) -> int | None:
    """Convierte un grupo de monto crudo (``"1,234,567"``) a entero de yenes.

    Args:
        raw: Texto capturado del monto, o ``None``.

    Returns:
        Entero de yenes, o ``None`` si no es un número válido.
    """
    if raw is None:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _first_match(text: str, patterns: list[re.Pattern[str]]) -> int | None:
    """Devuelve el primer monto que matchee alguno de los patrones, o ``None``.

    Args:
        text: Texto del PDF.
        patterns: Lista de regex (en orden de preferencia).

    Returns:
        Entero de yenes del primer match, o ``None``.
    """
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            value = _to_int(match.group(1))
            if value is not None:
                return value
    return None


def _parse_year(text: str) -> int | None:
    """Detecta el 年度 gregoriano desde 令和N年 / 平成N年 en el texto.

    令和元年 == 2019; 令和N年 == 2018 + N. 平成N年 == 1988 + N.

    Args:
        text: Texto del PDF.

    Returns:
        Año gregoriano del 年度, o ``None``.
    """
    reiwa = _REIWA_RE.search(text)
    if reiwa:
        token = reiwa.group(1)
        n = 1 if token == "元" else int(token)  # nosec B105
        return 2018 + n
    heisei = _HEISEI_RE.search(text)
    if heisei:
        token = heisei.group(1)
        n = 1 if token == "元" else int(token)  # nosec B105
        return 1988 + n
    return None


def extract_past_filing(pdf_bytes: bytes) -> ExtractedFiling:
    """Extrae los montos clave de un PDF de 確定申告 de un año anterior.

    Combina la extracción de texto (`pymupdf`) con regex tolerantes. Lo que no
    se detecta queda en ``None`` (nunca se inventa). Si el PDF no trae texto
    (escaneo) o `pymupdf` falta, devuelve un `ExtractedFiling` con ``raw_text``
    vacío y todos los campos ``None``.

    Args:
        pdf_bytes: Bytes del PDF subido.

    Returns:
        `ExtractedFiling` con los campos detectados.
    """
    text = extract_text_from_pdf(pdf_bytes)
    if not text:
        return ExtractedFiling(raw_text="")

    office_match = _TAX_OFFICE_RE.search(text)
    return ExtractedFiling(
        year=_parse_year(text),
        total_income=_first_match(text, _INCOME_RES),
        tax_paid=_first_match(text, _TAX_PAID_RES),
        tax_refund=_first_match(text, _TAX_REFUND_RES),
        tax_office=office_match.group(1) if office_match else None,
        raw_text=text,
    )
