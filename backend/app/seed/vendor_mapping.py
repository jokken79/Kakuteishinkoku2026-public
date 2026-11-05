"""Mapeo vendor -> 勘定科目 para auto-clasificacion de transacciones.

El mapeo vive como data en `vendor_mapping.json` (no hardcodeado en codigo) y
se carga en memoria. `classify_vendor` busca substrings (case-insensitive) del
nombre del vendor y devuelve el `code` de la cuenta sugerida.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import cast

logger = logging.getLogger(__name__)

_MAPPING_PATH = Path(__file__).parent / "vendor_mapping.json"


def load_vendor_mapping(path: Path | None = None) -> dict[str, str]:
    """Carga el mapeo vendor -> codigo de cuenta desde el JSON.

    Args:
        path: Ruta al JSON. Si es ``None`` usa `vendor_mapping.json` local.

    Returns:
        Diccionario {substring_vendor: codigo_cuenta}.
    """
    target = path or _MAPPING_PATH
    with target.open(encoding="utf-8") as fh:
        data = json.load(fh)
    mapping = data.get("mapping", {})
    logger.debug("Mapeo vendor cargado: %d reglas", len(mapping))
    return cast(dict[str, str], mapping)


# Mapeo cargado una vez al importar el modulo.
VENDOR_ACCOUNT_MAPPING: dict[str, str] = load_vendor_mapping()


def classify_vendor(
    vendor: str | None, mapping: dict[str, str] | None = None
) -> str | None:
    """Sugiere el codigo de cuenta para un vendor por coincidencia de substring.

    La comparacion es case-insensitive. Devuelve la primera regla que coincida.

    Args:
        vendor: Nombre del vendor/tienda (puede ser ``None``).
        mapping: Mapeo a usar. Si es ``None`` usa `VENDOR_ACCOUNT_MAPPING`.

    Returns:
        Codigo de cuenta sugerido, o ``None`` si no hay coincidencia.
    """
    if not vendor:
        return None
    rules = mapping if mapping is not None else VENDOR_ACCOUNT_MAPPING
    vendor_lower = vendor.lower()
    for needle, code in rules.items():
        if needle.lower() in vendor_lower:
            return code
    return None
