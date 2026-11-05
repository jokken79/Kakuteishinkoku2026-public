"""Parser del nombre del 取引先/店名 (vendor) desde el encabezado del recibo.

Heuristica simple y robusta: el nombre del comercio suele estar en las primeras
lineas del recibo. Se descartan lineas que son claramente metadata (fechas,
montos, 登録番号, telefono, codigo postal) y se toma la primera linea "texto"
significativa. No pretende ser perfecto: el campo es editable por el usuario.
"""

from __future__ import annotations

import re

# Lineas a ignorar como candidato a nombre (metadata, no razon social).
_NOISE_RE = re.compile(
    r"(登録番号|^T\d|〒|TEL|電話|\d{4}[.\-/年]\d|[¥￥]|円|合計|税込|税抜|消費税|"
    r"領収|レシート|No\.|\d{2,4}-\d{2,4}-\d{2,4})"
)
# Sufijos/prefijos tipicos de razon social japonesa (pista positiva).
_COMPANY_HINT_RE = re.compile(r"(株式会社|有限会社|\(株\)|（株）|店|商店|カフェ|薬局)")


def parse_vendor(raw_text: str) -> str | None:
    """Extrae el nombre del comercio del encabezado.

    Args:
        raw_text: Texto crudo del OCR.

    Returns:
        Nombre del vendor (primera linea significativa), o ``None`` si no se
        encuentra ninguna linea util.
    """
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return None

    # Prioridad 1: linea con pista de razon social dentro de las primeras 6.
    for line in lines[:6]:
        if _COMPANY_HINT_RE.search(line) and not _NOISE_RE.search(line):
            return line

    # Prioridad 2: primera linea no-ruido dentro de las primeras 4.
    for line in lines[:4]:
        if not _NOISE_RE.search(line):
            return line

    return None
