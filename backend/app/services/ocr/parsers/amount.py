"""Parser de montos (金額) sobre texto crudo de OCR.

Reconoce el total (合計/お買上げ/お買上/総額/ご請求額) y distingue 税抜
(sin impuesto) de 税込 (con impuesto). Limpia simbolos ``¥``/``円`` y separadores
de miles (``,``). Todos los montos son enteros (yenes, sin decimales).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Numero con simbolos: ¥1,200 / 1,200円 / ￥ 1200 / 1200.
_AMOUNT_RE = re.compile(r"[¥￥]?\s*([0-9０-９][0-9０-９,，]*)\s*円?")

# Palabras clave de total (prioridad alta -> baja).
_TOTAL_KEYWORDS = ("合計", "お買上げ", "お買上", "総額", "ご請求額", "請求金額", "計")
# Pistas de 税抜 (base sin impuesto).
_TAX_EXCLUDED_HINTS = ("税抜", "税別", "本体")
# Pistas de 税込 (con impuesto).
_TAX_INCLUDED_HINTS = ("税込", "内税")


@dataclass
class AmountInfo:
    """Monto extraido con su naturaleza fiscal.

    Args:
        total: Importe total detectado (entero en yenes), o ``None``.
        is_tax_included: ``True`` si el total es 税込, ``False`` si es 税抜,
            ``None`` si no se pudo determinar.
    """

    total: int | None = None
    is_tax_included: bool | None = None


def _normalize_digits(text: str) -> str:
    """Convierte digitos full-width a ASCII y quita separadores de miles.

    Args:
        text: Cadena con posibles digitos full-width y comas.

    Returns:
        Cadena solo con digitos ASCII.
    """
    trans = str.maketrans("０１２３４５６７８９，", "0123456789,")
    return text.translate(trans).replace(",", "")


def _to_int(group: str) -> int | None:
    """Convierte el grupo capturado a entero de yenes.

    Args:
        group: Substring numerico (posibles full-width/comas).

    Returns:
        Entero, o ``None`` si queda vacio.
    """
    digits = _normalize_digits(group)
    return int(digits) if digits else None


def parse_amount(raw_text: str) -> AmountInfo:
    """Extrae el monto total y si es 税込 o 税抜.

    Estrategia: busca la linea que contiene una palabra clave de total y toma el
    ultimo numero de esa linea. Si ninguna linea tiene keyword, usa el mayor
    numero del texto como heuristica de respaldo.

    Args:
        raw_text: Texto crudo del OCR.

    Returns:
        `AmountInfo` con el total y la naturaleza (税込/税抜) si se infiere.
    """
    lines = raw_text.splitlines()
    best: AmountInfo = AmountInfo()

    for line in lines:
        if not any(kw in line for kw in _TOTAL_KEYWORDS):
            continue
        numbers = _AMOUNT_RE.findall(line)
        values = [v for v in (_to_int(n) for n in numbers) if v is not None]
        if not values:
            continue
        # En una linea de total el importe suele ser el ultimo numero.
        total = values[-1]
        included: bool | None = None
        if any(h in line for h in _TAX_INCLUDED_HINTS):
            included = True
        elif any(h in line for h in _TAX_EXCLUDED_HINTS):
            included = False
        return AmountInfo(total=total, is_tax_included=included)

    # Respaldo: mayor numero del documento (probable total 税込).
    all_numbers = [
        v for v in (_to_int(n) for n in _AMOUNT_RE.findall(raw_text)) if v is not None
    ]
    if all_numbers:
        best = AmountInfo(total=max(all_numbers), is_tax_included=None)
    return best
