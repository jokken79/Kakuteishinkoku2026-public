"""Registry / factory de proveedores OCR (resuelve on/off + consentimiento).

Construye las instancias de proveedor a partir de `Settings`, expone su estado
(enabled / available / sends_data_externally) para el toggle del frontend y
resuelve el proveedor activo respetando:

1. El flag ``enabled`` por proveedor.
2. La disponibilidad real (`is_available()`): SDK instalado + credenciales.
3. El consentimiento `allow_external_ocr`: si es ``False`` se excluyen los
   proveedores con ``sends_data_externally=True``.

`resolve_chain` devuelve la lista ordenada de proveedores usables (primario +
fallbacks) para que el pipeline intente uno tras otro.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.services.ocr.base import OCRProvider
from app.services.ocr.providers import (
    AzureDocIntelligenceProvider,
    FakeOCRProvider,
    GeminiVisionProvider,
    GLMOCRProvider,
    GoogleDocAIProvider,
    OllamaOCRProvider,
    PaddleOCRProvider,
)
from app.services.ocr.quota import is_over_limit, over_limit_reason

logger = logging.getLogger(__name__)


@dataclass
class ProviderStatus:
    """Estado de un proveedor para el toggle on/off del frontend.

    Args:
        name: Nombre del proveedor.
        enabled: Flag de configuracion (prendido por el usuario).
        available: ``True`` si puede operar (SDK + credenciales presentes).
        sends_data_externally: ``True`` si el dato sale del equipo (cloud).
        usable: ``True`` si enabled & available & (local o consentido).
        reason: Motivo si no esta disponible (instrucciones), o ``None``.
    """

    name: str
    enabled: bool
    available: bool
    sends_data_externally: bool
    usable: bool
    reason: str | None = None


def build_providers(settings: Settings | None = None) -> dict[str, OCRProvider]:
    """Instancia todos los proveedores configurados.

    Args:
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.

    Returns:
        Diccionario ``{nombre: proveedor}`` (incluye los deshabilitados; el
        filtro de enabled se aplica al resolver, no al construir).
    """
    cfg = settings or get_settings()
    providers: dict[str, OCRProvider] = {
        "paddle": PaddleOCRProvider(lang=cfg.ocr_paddle_lang),
        "azure": AzureDocIntelligenceProvider(
            endpoint=cfg.ocr_azure_endpoint, api_key=cfg.ocr_azure_key
        ),
        "google": GoogleDocAIProvider(
            project_id=cfg.ocr_google_project_id,
            location=cfg.ocr_google_location,
            processor_id=cfg.ocr_google_processor_id,
        ),
        "gemini": GeminiVisionProvider(
            api_key=cfg.ocr_gemini_api_key, model=cfg.ocr_gemini_model
        ),
        "glm": GLMOCRProvider(
            api_key=cfg.ocr_glm_api_key,
            api_url=cfg.ocr_glm_api_url,
            ollama_url=cfg.ocr_glm_ollama_url,
            model=cfg.ocr_glm_model,
        ),
        "ollama": OllamaOCRProvider(
            ollama_url=cfg.ocr_ollama_url,
            model=cfg.ocr_ollama_model,
        ),
        "fake": FakeOCRProvider(),
    }
    return providers


def _enabled_flag(cfg: Settings, name: str) -> bool:
    """Devuelve el flag ``enabled`` de un proveedor por nombre."""
    return bool(getattr(cfg, f"ocr_{name}_enabled", False))


def provider_statuses(settings: Settings | None = None) -> list[ProviderStatus]:
    """Calcula el estado de todos los proveedores.

    Args:
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.

    Returns:
        Lista de `ProviderStatus`, util para `GET /ocr/providers`.
    """
    from app.services.ocr.runtime_settings import apply_overrides

    cfg = apply_overrides(settings or get_settings())
    providers = build_providers(cfg)
    statuses: list[ProviderStatus] = []
    for name, provider in providers.items():
        enabled = _enabled_flag(cfg, name)
        available = provider.is_available()
        external = provider.sends_data_externally
        consent_ok = (not external) or cfg.allow_external_ocr
        over_quota = is_over_limit(name, settings=cfg)
        usable = enabled and available and consent_ok and not over_quota
        reason = provider.unavailable_reason()
        if available and external and not cfg.allow_external_ocr:
            reason = (
                "Proveedor cloud bloqueado: requiere consentimiento "
                "(allow_external_ocr=True) para enviar el dato fuera del equipo."
            )
        elif available and over_quota:
            reason = over_limit_reason(name, settings=cfg)
        statuses.append(
            ProviderStatus(
                name=name,
                enabled=enabled,
                available=available,
                sends_data_externally=external,
                usable=usable,
                reason=reason,
            )
        )
    return statuses


def resolve_chain(settings: Settings | None = None) -> list[OCRProvider]:
    """Resuelve la cadena ordenada de proveedores usables.

    Orden: `ocr_primary` primero, luego `ocr_fallback_chain` (sin duplicar),
    quedandose solo con los proveedores enabled + available + consentidos.

    Args:
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.

    Returns:
        Lista de proveedores usables en orden de preferencia (puede ser vacia).
    """
    from app.services.ocr.runtime_settings import apply_overrides

    cfg = apply_overrides(settings or get_settings())
    providers = build_providers(cfg)

    order: list[str] = []
    for name in [cfg.ocr_primary, *cfg.ocr_fallback_chain]:
        if name not in order:
            order.append(name)

    chain: list[OCRProvider] = []
    for name in order:
        provider = providers.get(name)
        if provider is None:
            logger.warning("OCR provider desconocido en config: %s", name)
            continue
        if not _enabled_flag(cfg, name):
            continue
        if not provider.is_available():
            continue
        if provider.sends_data_externally and not cfg.allow_external_ocr:
            logger.info("Provider '%s' excluido: sin consentimiento externo", name)
            continue
        # Cuota diaria del free tier: si el provider cloud ya alcanzo su limite
        # hoy (zona Pacific), queda no-usable -> se salta (cae al fallback local).
        if is_over_limit(name, settings=cfg):
            logger.info(
                "Provider '%s' excluido por cuota: %s",
                name, over_limit_reason(name, settings=cfg),
            )
            continue
        chain.append(provider)
    return chain
