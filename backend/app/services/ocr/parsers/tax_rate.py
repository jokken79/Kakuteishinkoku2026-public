"""Parser de tasas de consumo (消費税率) y split 軽減税率 (8% / 10%).

Lee bloques tipo ``内8%対象 ¥1,080`` / ``内10%対象 ¥2,200`` y el detalle de
``(内消費税...)`` para separar la operacion en lineas por tasa. Cada linea
representa un grupo de区分経理 con ``base`` (税抜), ``tax`` (消費税額) y la tasa.

Cuando solo aparece una tasa, devuelve una sola linea. Si el texto da el monto
``対象`` (que suele ser 税込 del grupo) y el ``消費税``, deriva la base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 内8%対象 1,080円 / 8%対象 ¥1080 / 軽減 8% ...
_TARGET_RE = re.compile(
    r"(?:内)?\s*(10|8)\s*[%％]\s*対象\s*[:：]?\s*[¥￥]?\s*([0-9０-９,，]+)"
)
# (内消費税 80円) / 消費税(8%) 80 / うち消費税...
_TAX_AMOUNT_RE = re.compile(
    r"(?:内|うち)?\s*消費税\s*[(（]?\s*(10|8)?\s*[%％]?\s*[)）]?\s*[:：]?\s*[¥￥]?\s*([0-9０-９,，]+)"
)
# Mencion suelta de una tasa (10% / 8%) sin "対象".
_RATE_MENTION_RE = re.compile(r"(10|8)\s*[%％]")


@dataclass
class TaxLine:
    """Linea de区分経理 por tasa.

    Args:
        rate: Tasa de consumo (10 u 8).
        base: Importe 税抜 (base imponible), o ``None`` si no se pudo derivar.
        tax: Importe del 消費税 de ese grupo, o ``None``.
    """

    rate: int
    base: int | None = None
    tax: int | None = None


def _to_int(group: str | None) -> int | None:
    """Normaliza full-width/comas y convierte a entero (o ``None``)."""
    if not group:
        return None
    trans = str.maketrans("０１２３４５６７８９，", "0123456789,")
    digits = group.translate(trans).replace(",", "")
    return int(digits) if digits else None


def parse_tax_lines(raw_text: str, total: int | None = None) -> list[TaxLine]:
    """Extrae lineas por tasa (8% / 10%) del texto del recibo.

    Combina los bloques ``対象`` (monto 税込 del grupo) con los ``消費税``
    (importe del impuesto) para reconstruir base y tax de cada tasa.

    Muchos recibos termicos de UNA sola tasa dan el ``合計（税込）`` y el
    ``内消費税`` pero **no** un bloque ``内N%対象``. En ese caso, si se conoce el
    ``total`` 税込, se deriva ``base = total - tax`` para que el cuadre aritmetico
    cierre (research §5: maximizar lo que se extrae del texto disponible).

    Args:
        raw_text: Texto crudo del OCR.
        total: Total 税込 del recibo (de `parse_amount`), para derivar la base
            cuando hay una sola tasa sin bloque ``対象``. ``None`` si no se conoce.

    Returns:
        Lista de `TaxLine` ordenada por tasa descendente (10% antes que 8%).
        Lista vacia si no se detecta ninguna tasa.
    """
    # rate -> monto del bloque 対象 (suele ser 税込 del grupo).
    target_by_rate: dict[int, int] = {}
    for rate_str, amount_str in _TARGET_RE.findall(raw_text):
        amount = _to_int(amount_str)
        if amount is not None:
            target_by_rate[int(rate_str)] = amount

    # rate -> 消費税額 explicito.
    tax_by_rate: dict[int, int] = {}
    untagged_tax: list[int] = []
    for rate_str, amount_str in _TAX_AMOUNT_RE.findall(raw_text):
        amount = _to_int(amount_str)
        if amount is None:
            continue
        if rate_str:
            tax_by_rate[int(rate_str)] = amount
        else:
            untagged_tax.append(amount)

    rates = set(target_by_rate) | set(tax_by_rate)
    if not rates:
        # Sin bloques explicitos: detectar una sola tasa mencionada.
        mentioned = {int(r) for r in _RATE_MENTION_RE.findall(raw_text)}
        if untagged_tax and len(mentioned) == 1:
            rate = next(iter(mentioned))
            single_tax = untagged_tax[0]
            # Si conocemos el total 税込, derivar la base (cierra el cuadre).
            single_base = total - single_tax if total is not None else None
            return [TaxLine(rate=rate, base=single_base, tax=single_tax)]
        return [TaxLine(rate=rate) for rate in sorted(mentioned, reverse=True)]

    lines: list[TaxLine] = []
    single_rate = len(rates) == 1
    for rate in sorted(rates, reverse=True):
        gross = target_by_rate.get(rate)
        tax = tax_by_rate.get(rate)
        base = None
        if gross is not None and tax is not None:
            # 対象 es 税込 del grupo -> base = gross - tax.
            base = gross - tax
        elif gross is not None:
            # Derivar impuesto desde el bruto del grupo: tax = gross*rate/(100+rate).
            tax = round(gross * rate / (100 + rate))
            base = gross - tax
        elif tax is not None and single_rate and total is not None:
            # Una sola tasa, sin bloque 対象 pero con total 税込: base = total - tax.
            base = total - tax
        lines.append(TaxLine(rate=rate, base=base, tax=tax))
    return lines
