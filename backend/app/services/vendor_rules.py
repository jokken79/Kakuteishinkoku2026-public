"""Reglas aprendidas 取引先 -> 勘定科目 (memoria del clasificador).

La app aprende de lo que el usuario confirma: cuando acepta o corrige el 科目
propuesto para un recibo, se refuerza la regla de ese 取引先 (`VendorAccountRule`).
La proxima foto de la misma tienda ya llega con el 科目 correcto propuesto, asi
la revision baja a un toque.

Piezas:

- `normalize_vendor` — clave estable del 取引先 (NFKC, minusculas, sin espacios
  ni sufijos societarios), para que "セブン-イレブン 渋谷店" y "セブンイレブン"
  compartan regla.
- `lookup_rule` — busca por clave exacta y, si no hay, por la regla mas larga
  contenida en la clave (cubre sucursales: `...渋谷店`).
- `learn_rule` — upsert que refuerza (`hits`) o reapunta la regla a otro 科目.
- `LearnedAccountClassifier` — implementacion de `AccountClassifier` que
  antepone lo aprendido al mapeo semilla; se inyecta en `process_receipt`.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import VendorAccountRule
from app.services.ocr.classifier import (
    AccountClassifier,
    AccountSuggestion,
    RuleAccountClassifier,
)

logger = logging.getLogger(__name__)

# Confianza de una sugerencia aprendida: por encima de la regla semilla (0.8),
# porque la eligio el propio usuario para ese 取引先.
_LEARNED_CONFIDENCE = 0.95
# Longitud minima de clave para permitir match por substring (evita que una
# regla de 1-2 caracteres se coma cualquier vendor).
_MIN_SUBSTRING_KEY = 3
# Sufijos/prefijos societarios que no aportan identidad al 取引先.
_COMPANY_AFFIXES = (
    "株式会社",
    "有限会社",
    "合同会社",
    "合資会社",
    "合名会社",
    "㈱",
    "㈲",
    "(株)",
    "(有)",
)
# Todo lo que no sea letra/numero/kana/kanji se descarta de la clave.
# (tras NFKC ya no quedan 半角カナ, asi que alcanza con hiragana/katakana/kanji).
_NON_WORD = re.compile(r"[^0-9a-z぀-ヿ㐀-鿿]+")


def normalize_vendor(vendor: str | None) -> str:
    """Normaliza un nombre de 取引先 a una clave estable de regla.

    Aplica NFKC (半角/全角 unificados), pasa a minusculas, saca los sufijos
    societarios y descarta espacios y puntuacion.

    Args:
        vendor: Nombre del 取引先 tal como lo leyo el OCR (puede ser ``None``).

    Returns:
        Clave normalizada, o cadena vacia si no hay nombre utilizable.
    """
    if not vendor:
        return ""
    text = unicodedata.normalize("NFKC", vendor).strip().lower()
    for affix in _COMPANY_AFFIXES:
        text = text.replace(unicodedata.normalize("NFKC", affix).lower(), "")
    return _NON_WORD.sub("", text)


def lookup_rule(db: Session, vendor: str | None) -> VendorAccountRule | None:
    """Busca la regla aprendida que aplica a un 取引先.

    Primero por clave exacta; si no hay, por la regla mas larga contenida en la
    clave del vendor (asi `セブンイレブン渋谷店` usa la regla `セブンイレブン`).

    Args:
        db: Sesion de BD.
        vendor: Nombre del 取引先 leido por el OCR.

    Returns:
        La `VendorAccountRule` aplicable, o ``None`` si no hay ninguna.
    """
    key = normalize_vendor(vendor)
    if not key:
        return None
    exact = db.scalars(
        select(VendorAccountRule).where(VendorAccountRule.vendor_key == key)
    ).first()
    if exact is not None:
        return exact

    candidates = [
        rule
        for rule in db.scalars(select(VendorAccountRule)).all()
        if len(rule.vendor_key) >= _MIN_SUBSTRING_KEY and rule.vendor_key in key
    ]
    if not candidates:
        return None
    # La clave mas larga es la mas especifica; a igual largo, la mas usada.
    return max(candidates, key=lambda r: (len(r.vendor_key), r.hits))


def learn_rule(
    db: Session, vendor: str | None, account_code: str | None
) -> VendorAccountRule | None:
    """Aprende (o refuerza) la regla 取引先 -> 勘定科目 de una confirmacion.

    No hace commit: lo deja al llamador, que ya maneja la transaccion.

    Args:
        db: Sesion de BD.
        vendor: Nombre del 取引先 de la transaccion confirmada.
        account_code: 勘定科目 con el que quedo confirmada.

    Returns:
        La regla creada/actualizada, o ``None`` si no hay datos suficientes.
    """
    key = normalize_vendor(vendor)
    if not key or not account_code:
        return None

    now = _dt.datetime.now(_dt.UTC)
    rule = db.scalars(
        select(VendorAccountRule).where(VendorAccountRule.vendor_key == key)
    ).first()
    if rule is None:
        rule = VendorAccountRule(
            vendor_key=key,
            vendor_sample=(vendor or "")[:255] or None,
            account_code=account_code,
            hits=1,
            last_used_at=now,
        )
        db.add(rule)
        db.flush()
        return rule

    if rule.account_code == account_code:
        rule.hits += 1
    else:
        # El usuario cambio de opinion: la regla se reapunta y vuelve a contar.
        rule.account_code = account_code
        rule.hits = 1
    rule.vendor_sample = (vendor or "")[:255] or rule.vendor_sample
    rule.last_used_at = now
    db.flush()
    return rule


class LearnedAccountClassifier:
    """Clasificador de 科目 que antepone lo aprendido al mapeo semilla.

    Implementa `AccountClassifier`. Si el 取引先 tiene una regla aprendida, la
    devuelve con confianza alta (`source="learned"`); si no, delega en el
    clasificador por reglas del seed.
    """

    def __init__(self, db: Session, fallback: AccountClassifier | None = None) -> None:
        """Crea el clasificador.

        Args:
            db: Sesion de BD donde viven las reglas aprendidas.
            fallback: Clasificador de respaldo (default: `RuleAccountClassifier`).
        """
        self._db = db
        self._fallback = fallback or RuleAccountClassifier()

    def suggest(self, vendor: str | None, raw_text: str = "") -> AccountSuggestion:
        """Sugiere el 科目 para un 取引先, priorizando lo aprendido.

        Args:
            vendor: Nombre del 取引先/店名.
            raw_text: Texto crudo del recibo (fallback del seed).

        Returns:
            `AccountSuggestion` con `source="learned"` si hubo regla aprendida.
        """
        rule = lookup_rule(self._db, vendor)
        if rule is not None:
            return AccountSuggestion(
                account_code=rule.account_code,
                confidence=_LEARNED_CONFIDENCE,
                source="learned",
            )
        return self._fallback.suggest(vendor, raw_text)
