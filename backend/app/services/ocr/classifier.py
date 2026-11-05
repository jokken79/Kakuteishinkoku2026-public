"""Clasificador de 勘定科目 a partir del vendor del recibo.

Reusa el mapeo vendor->codigo del seed (`app.seed.vendor_mapping.classify_vendor`)
en lugar de duplicarlo. Devuelve el codigo de cuenta sugerido y una confianza.

Se deja un hook (`MLAccountClassifier`, interfaz sin implementacion) para el
clasificador incremental futuro que aprenda del historial de 仕訳 confirmados.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.seed.vendor_mapping import classify_vendor

logger = logging.getLogger(__name__)

# Cuenta por defecto cuando no hay coincidencia (雑費 — gasto misceláneo).
_DEFAULT_ACCOUNT_CODE = "599"


@dataclass
class AccountSuggestion:
    """Sugerencia de 勘定科目 para una transaccion.

    Args:
        account_code: Codigo de cuenta sugerido.
        confidence: Confianza de la sugerencia (0.0-1.0).
        source: Origen de la sugerencia (``rule`` | ``ml`` | ``default``).
    """

    account_code: str
    confidence: float
    source: str


@runtime_checkable
class AccountClassifier(Protocol):
    """Interfaz de un clasificador de 勘定科目."""

    def suggest(self, vendor: str | None, raw_text: str = "") -> AccountSuggestion:
        """Sugiere una cuenta para el vendor/texto dado.

        Args:
            vendor: Nombre del 取引先/店名.
            raw_text: Texto crudo completo (para reglas sobre 品目).

        Returns:
            `AccountSuggestion` con codigo, confianza y origen.
        """
        ...


class RuleAccountClassifier:
    """Clasificador determinista por reglas vendor->科目 (seed)."""

    def suggest(self, vendor: str | None, raw_text: str = "") -> AccountSuggestion:
        """Sugiere una cuenta por coincidencia de substring del vendor.

        Args:
            vendor: Nombre del 取引先/店名.
            raw_text: Texto crudo (fallback: se busca el match tambien aqui).

        Returns:
            `AccountSuggestion`. Si no hay match, devuelve la cuenta por defecto
            (雑費) con confianza baja.
        """
        code = classify_vendor(vendor)
        if code is None and raw_text:
            # Respaldo: buscar el mapeo en el texto completo (encabezado ruidoso).
            code = classify_vendor(raw_text)
        if code is not None:
            return AccountSuggestion(account_code=code, confidence=0.8, source="rule")
        return AccountSuggestion(
            account_code=_DEFAULT_ACCOUNT_CODE, confidence=0.2, source="default"
        )


class MLAccountClassifier:
    """Hook para el clasificador ML incremental (no implementado aun).

    Aprenderia del historial de 仕訳 confirmados del usuario para sugerir
    cuentas a vendors nuevos. Por ahora delega en el clasificador por reglas.
    """

    def __init__(self, fallback: AccountClassifier | None = None) -> None:
        self._fallback = fallback or RuleAccountClassifier()

    def suggest(self, vendor: str | None, raw_text: str = "") -> AccountSuggestion:
        """Delega en el fallback por reglas (placeholder del ML futuro).

        Args:
            vendor: Nombre del 取引先/店名.
            raw_text: Texto crudo.

        Returns:
            `AccountSuggestion` del clasificador de respaldo.
        """
        # TODO(fase-ML): entrenar sobre JournalEntry confirmados y combinar scores.
        return self._fallback.suggest(vendor, raw_text)


def get_default_classifier() -> AccountClassifier:
    """Devuelve el clasificador por defecto del pipeline (reglas).

    Returns:
        Instancia de `RuleAccountClassifier`.
    """
    return RuleAccountClassifier()
