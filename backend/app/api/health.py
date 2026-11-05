"""Router de healthcheck.

Expone un endpoint liviano para verificar que el servicio esta vivo. Lo usa el
frontend (badge de conexion) y, a futuro, los health probes de docker/CI.
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Respuesta del endpoint de salud.

    Args:
        status: Estado del servicio ("ok" cuando esta operativo).
        service: Nombre del servicio.
        version: Version del servicio.
    """

    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Verifica que el servicio responde.

    Returns:
        Estado, nombre y version del servicio.
    """
    settings = get_settings()
    logger.debug("Healthcheck solicitado")
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )
