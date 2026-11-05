"""Parser y validador del 登録番号 (numero de registro インボイス).

Formato: ``T`` + 13 digitos (los 13 digitos son un 法人番号 valido, o el
番号 de una persona fisica). El ultimo digito de los 13 es un digito de control.

Algoritmo de checksum del 法人番号 (nota: el numero completo son 13 digitos;
el primero es el digito de control `C` y los 12 restantes `P1..P12` la base):

    C = 9 - ( Σ (Pn * Qn) mod 9 )

donde ``Qn = 1`` para posiciones impares (contadas desde la mas baja) y ``2``
para las pares. Es decir, recorriendo los 12 digitos base de derecha a izquierda,
se alterna peso 1, 2, 1, 2, ...

Tolerancias de OCR: ``T`` puede confundirse con ``〒`` o estar separado por
salto de linea/espacios de los digitos; puede haber multiples numeros.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# T (o 〒, o t) seguido — con posible ruido — de 13 digitos.
# Permitimos espacios, saltos de linea y guiones entre la letra y los digitos,
# y entre los propios digitos (que luego se limpian).
_CANDIDATE_RE = re.compile(
    r"[T〒tＴ]\s*[-\s]?\s*((?:\d[\s\-]?){13})"
)


@dataclass
class RegistrationNumber:
    """登録番号 detectado.

    Args:
        value: Numero normalizado ``T`` + 13 digitos.
        is_valid_checksum: ``True`` si el digito de control es correcto.
    """

    value: str
    is_valid_checksum: bool


def validate_checksum(digits13: str) -> bool:
    """Valida el digito de control de un 法人番号 (13 digitos).

    Args:
        digits13: Cadena de exactamente 13 digitos.

    Returns:
        ``True`` si el primer digito (control) coincide con el calculado sobre
        los 12 restantes; ``False`` si no, o si la longitud no es 13.
    """
    if len(digits13) != 13 or not digits13.isdigit():
        return False
    check = int(digits13[0])
    base = digits13[1:]  # P1..P12 (P1 = mas significativo).
    # Recorrer de derecha a izquierda: peso 1, 2, 1, 2, ...
    total = 0
    for idx, ch in enumerate(reversed(base)):
        weight = 1 if idx % 2 == 0 else 2
        total += int(ch) * weight
    computed = 9 - (total % 9)
    return computed == check


def find_registration_numbers(raw_text: str) -> list[RegistrationNumber]:
    """Encuentra todos los 登録番号 candidatos del texto.

    Tolera ``T``/``〒`` confundidos, espacios y saltos de linea dentro del numero.

    Args:
        raw_text: Texto crudo del OCR.

    Returns:
        Lista de `RegistrationNumber` (con su validez de checksum). Puede ser
        vacia. No deduplica salvo numeros identicos ya normalizados.
    """
    found: list[RegistrationNumber] = []
    seen: set[str] = set()
    for match in _CANDIDATE_RE.finditer(raw_text):
        digits = re.sub(r"[\s\-]", "", match.group(1))
        if len(digits) != 13:
            continue
        value = f"T{digits}"
        if value in seen:
            continue
        seen.add(value)
        found.append(
            RegistrationNumber(value=value, is_valid_checksum=validate_checksum(digits))
        )
    return found


def parse_registration_number(raw_text: str) -> RegistrationNumber | None:
    """Devuelve el mejor 登録番号 del texto (prefiere checksum valido).

    Args:
        raw_text: Texto crudo del OCR.

    Returns:
        El primer numero con checksum valido; si ninguno valida, el primero
        encontrado; ``None`` si no hay candidatos.
    """
    candidates = find_registration_numbers(raw_text)
    if not candidates:
        return None
    for candidate in candidates:
        if candidate.is_valid_checksum:
            return candidate
    return candidates[0]
