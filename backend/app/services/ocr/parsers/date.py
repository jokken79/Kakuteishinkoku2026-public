"""Parser de fechas japonesas (日付) sobre texto crudo de OCR.

Soporta:
- Eras 令和/平成/昭和 en kanji (`令和6年5月3日`) y abreviadas (`R6.5.3`, `H30.1.1`).
- Calendario gregoriano / seireki (`2026-05-03`, `2026/5/3`, `2026年5月3日`).

Convierte la era a anio gregoriano (令和N -> 2018+N, 平成N -> 1988+N,
昭和N -> 1925+N; el anio 1 de cada era se cuenta correctamente porque
令和1 = 2019 = 2018+1). Rechaza fechas futuras respecto a ``today``.
"""

from __future__ import annotations

import datetime
import re

# Offsets de era: era_year + offset = anio gregoriano.
_ERA_OFFSETS: dict[str, int] = {
    "令和": 2018,
    "R": 2018,
    "平成": 1988,
    "H": 1988,
    "昭和": 1925,
    "S": 1925,
}

# 令和6年5月3日 / 令和元年... ('元' = year 1).
_ERA_KANJI_RE = re.compile(
    r"(令和|平成|昭和)\s*(元|\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
# R6.5.3 / H30/1/1 / R6-5-3 (era abreviada con separadores).
_ERA_ABBR_RE = re.compile(
    r"(?<![A-Za-z])([RHS])\s*(\d{1,2})\s*[.\-/年]\s*(\d{1,2})\s*[.\-/月]\s*(\d{1,2})"
)
# 2026年5月3日 / 2026-05-03 / 2026/5/3.
_SEIREKI_RE = re.compile(
    r"(\d{4})\s*[.\-/年]\s*(\d{1,2})\s*[.\-/月]\s*(\d{1,2})"
)


def _to_gregorian(era: str, era_year: int) -> int:
    """Convierte (era, anio_de_era) a anio gregoriano.

    Args:
        era: Nombre de era (kanji o letra abreviada).
        era_year: Anio dentro de la era (``元`` ya resuelto a 1).

    Returns:
        Anio gregoriano correspondiente.
    """
    return _ERA_OFFSETS[era] + era_year


def parse_date(
    raw_text: str, *, today: datetime.date | None = None
) -> datetime.date | None:
    """Extrae la primera fecha plausible del texto.

    Prueba en orden: era kanji, era abreviada, seireki. Descarta fechas futuras
    (posteriores a ``today``) e invalidas (ej. mes 13).

    Args:
        raw_text: Texto crudo del OCR.
        today: Fecha de referencia para el filtro de futuro (default: hoy).

    Returns:
        `datetime.date` de la primera coincidencia valida, o ``None``.
    """
    ref = today or datetime.date.today()
    candidates: list[tuple[int, int, int]] = []

    for match in _ERA_KANJI_RE.finditer(raw_text):
        era, ey, mm, dd = match.groups()
        era_year = 1 if ey == "元" else int(ey)
        candidates.append((_to_gregorian(era, era_year), int(mm), int(dd)))

    for match in _ERA_ABBR_RE.finditer(raw_text):
        era, ey, mm, dd = match.groups()
        candidates.append((_to_gregorian(era, int(ey)), int(mm), int(dd)))

    for match in _SEIREKI_RE.finditer(raw_text):
        yy, mm, dd = match.groups()
        candidates.append((int(yy), int(mm), int(dd)))

    for year, month, day in candidates:
        try:
            value = datetime.date(year, month, day)
        except ValueError:
            continue
        if value <= ref:
            return value
    return None
