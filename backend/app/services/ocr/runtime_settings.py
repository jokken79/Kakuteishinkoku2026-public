"""Persistencia runtime de la configuracion OCR (toggles del frontend).

`Settings` (pydantic-settings) carga la config base desde env/.env y es la
fuente de la *configuracion por defecto*. Pero los toggles del frontend
(prender/apagar un proveedor, el switch maestro ``allow_external_ocr``) deben
**persistir en runtime** sin reiniciar el proceso ni reescribir `.env`.

Este modulo provee una capa de override en disco (JSON) que se superpone a los
defaults de `Settings`:

- ``get_overrides()``  lee el JSON (vacio si no existe).
- ``apply_overrides(settings)`` devuelve una copia de `Settings` con los
  overrides aplicados (lo usa el registry para resolver el estado/cadena).
- ``patch_overrides(...)`` valida y persiste cambios parciales.

Solo se permiten overrides de campos *no sensibles*: los flags ``enabled`` por
proveedor y ``allow_external_ocr``. Las credenciales NUNCA se tocan por aca (van
solo por env, ver `.claude/rules/security.md`).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Proveedores cuyos flags ``enabled`` se pueden togglear desde el frontend.
# 'ollama' es OCR 100% local (privado, $0): toggleable pero NO en QUOTA_PROVIDERS
# (el dato no sale del equipo, no consume cuota cloud).
TOGGLEABLE_PROVIDERS: tuple[str, ...] = (
    "paddle", "ollama", "azure", "google", "gemini", "glm",
)

# Proveedores cloud cuyo limite diario de cuota se puede ajustar en runtime.
QUOTA_PROVIDERS: tuple[str, ...] = ("gemini", "glm", "azure", "google")

# Lock de proceso para escrituras atomicas del JSON.
_LOCK = threading.Lock()


def _overrides_path(settings: Settings | None = None) -> Path:
    """Ruta del JSON de overrides (junto a la carpeta de evidencia/data).

    Args:
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.

    Returns:
        Ruta del archivo ``ocr_settings.json``.
    """
    cfg = settings or get_settings()
    # Lo guardamos al lado de evidence_dir (carpeta `data/` por defecto).
    base = Path(cfg.evidence_dir).parent
    return base / "ocr_settings.json"


def get_overrides(settings: Settings | None = None) -> dict[str, Any]:
    """Lee los overrides persistidos (``{}`` si no hay archivo).

    Args:
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.

    Returns:
        Diccionario con los overrides (claves: ``allow_external_ocr`` y
        ``ocr_<name>_enabled``). Vacio si el archivo no existe o esta corrupto.
    """
    path = _overrides_path(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("No se pudo leer overrides OCR (%s): %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def apply_overrides(settings: Settings) -> Settings:
    """Devuelve una copia de `Settings` con los overrides runtime aplicados.

    Args:
        settings: Settings base (defaults de env/.env).

    Returns:
        Copia de `Settings` con ``allow_external_ocr`` y los flags ``enabled``
        sobreescritos por lo persistido en runtime (si existe).
    """
    overrides = get_overrides(settings)
    if not overrides:
        return settings
    updates: dict[str, Any] = {}
    if "allow_external_ocr" in overrides:
        updates["allow_external_ocr"] = bool(overrides["allow_external_ocr"])
    for name in TOGGLEABLE_PROVIDERS:
        key = f"ocr_{name}_enabled"
        if key in overrides:
            updates[key] = bool(overrides[key])
    # Limites diarios de cuota ajustables en runtime (override del default/env).
    for name in QUOTA_PROVIDERS:
        key = f"ocr_{name}_daily_limit"
        if key in overrides:
            try:
                value = int(overrides[key])
            except (TypeError, ValueError):
                continue
            if value > 0:
                updates[key] = value
    if not updates:
        return settings
    return settings.model_copy(update=updates)


def patch_overrides(
    *,
    allow_external_ocr: bool | None = None,
    providers: dict[str, bool] | None = None,
    daily_limits: dict[str, int] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Persiste cambios parciales de los toggles OCR (atomico).

    Args:
        allow_external_ocr: Nuevo valor del switch maestro, o ``None`` para no
            tocarlo.
        providers: Mapa ``{nombre: enabled}`` con los flags a actualizar. Solo
            se aceptan nombres en `TOGGLEABLE_PROVIDERS`.
        daily_limits: Mapa ``{nombre: limite}`` con los limites diarios de cuota
            a actualizar. Solo se aceptan nombres en `QUOTA_PROVIDERS` y valores
            enteros positivos.
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.

    Returns:
        El diccionario completo de overrides ya persistido.

    Raises:
        ValueError: Si se intenta togglear un proveedor desconocido o el 'fake',
            o ajustar la cuota de un proveedor no-cloud o con un valor invalido.
    """
    cfg = settings or get_settings()
    path = _overrides_path(cfg)

    with _LOCK:
        current = get_overrides(cfg)
        if allow_external_ocr is not None:
            current["allow_external_ocr"] = bool(allow_external_ocr)
        if providers:
            for name, enabled in providers.items():
                if name not in TOGGLEABLE_PROVIDERS:
                    raise ValueError(f"Proveedor no toggleable: {name!r}")
                current[f"ocr_{name}_enabled"] = bool(enabled)
        if daily_limits:
            for name, limit in daily_limits.items():
                if name not in QUOTA_PROVIDERS:
                    raise ValueError(f"Proveedor sin cuota cloud: {name!r}")
                if not isinstance(limit, int) or limit <= 0:
                    raise ValueError(
                        f"Limite diario invalido para {name!r}: {limit!r} (debe ser >0)."
                    )
                current[f"ocr_{name}_daily_limit"] = limit

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    logger.info("Overrides OCR persistidos en %s", path)
    return current
