"""Ensemble / consensus por campo (voto multi-engine, research §5.4).

Cuando la validacion de un recibo es **bloqueante** (cuadre/registro fallan) o la
confianza es **baja**, correr un SEGUNDO provider y votar campo a campo lleva la
precision "al limite" (CER -30/50% segun el research):

- Si los dos providers **coinciden** en un campo -> alta confianza en ese campo.
- Si **discrepan** -> el campo se marca como dudoso y el recibo queda ``pending``
  (consensus entropy: el arbitro real sigue siendo la validacion aritmetica).

Este modulo es logica pura sobre dos `ParsedReceipt`: no resuelve la cadena ni
llama a providers (eso lo hace el pipeline, que ademas respeta el consentimiento
``allow_external_ocr`` al elegir el segundo provider).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.ocr.parsers import ParsedReceipt

logger = logging.getLogger(__name__)

# Campos criticos que se votan en el consenso.
_VOTED_FIELDS = ("date", "vendor", "total", "registration_number")


@dataclass
class ConsensusResult:
    """Resultado del voto campo a campo entre dos parseos.

    Args:
        agreed_fields: Campos en los que ambos providers coinciden.
        disputed_fields: Campos en los que discrepan (quedan dudosos).
        agreement_ratio: Proporcion de campos comparables que coincidieron.
        notes: Mensajes legibles de cada discrepancia.
    """

    agreed_fields: list[str] = field(default_factory=list)
    disputed_fields: list[str] = field(default_factory=list)
    agreement_ratio: float = 1.0
    notes: list[str] = field(default_factory=list)

    @property
    def has_disputes(self) -> bool:
        """``True`` si hubo al menos un campo en disputa."""
        return bool(self.disputed_fields)


def _field_value(parsed: ParsedReceipt, name: str) -> object:
    """Obtiene el valor comparable de un campo (normaliza tax_lines aparte)."""
    return getattr(parsed, name, None)


def vote_fields(primary: ParsedReceipt, secondary: ParsedReceipt) -> ConsensusResult:
    """Vota campo a campo entre el parseo primario y el secundario.

    Solo compara campos que **ambos** providers detectaron (ambos no-``None``):
    si uno no lo leyo no hay desacuerdo real (un provider puede complementar al
    otro). Los campos comparables que difieren se marcan en disputa.

    Args:
        primary: Recibo parseado del provider primario.
        secondary: Recibo parseado del provider secundario (2do voto).

    Returns:
        `ConsensusResult` con campos coincidentes, en disputa y el ratio.
    """
    result = ConsensusResult()
    comparable = 0
    for name in _VOTED_FIELDS:
        a = _field_value(primary, name)
        b = _field_value(secondary, name)
        if a is None or b is None:
            continue  # no comparable: un provider no lo leyo.
        comparable += 1
        if a == b:
            result.agreed_fields.append(name)
        else:
            result.disputed_fields.append(name)
            result.notes.append(f"Discrepancia en {name}: primario={a!r} vs 2do={b!r}.")

    result.agreement_ratio = (
        len(result.agreed_fields) / comparable if comparable else 1.0
    )
    if result.has_disputes:
        logger.info(
            "Consenso con disputas (%d/%d coinciden): %s",
            len(result.agreed_fields),
            comparable,
            ", ".join(result.disputed_fields),
        )
    return result
