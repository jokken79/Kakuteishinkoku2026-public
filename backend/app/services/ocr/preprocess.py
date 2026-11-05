"""Preprocesamiento de imagen ANTES del OCR (mayor salto de precision).

El research §5 marca el preproceso como el paso de **mayor impacto** para llevar
recibos japoneses (termicos desvanecidos, inclinados, de baja resolucion) de
``<70%`` a ``>95%`` de precision, sin GPU y antes de cualquier proveedor.

Pipeline (todo con OpenCV + Pillow):

    bytes -> decode (gris) -> deskew (corrige inclinacion) -> CLAHE (contraste,
    rescata termicos) -> denoise -> binarizacion adaptativa (Otsu) -> upscale ×2
    condicional (si la imagen es chica/borrosa) -> re-encode a PNG -> bytes

Diseño defensivo (Capa 4 — Observabilidad / degradacion):

- **OpenCV es opcional**: si ``cv2`` (o ``numpy``) no esta instalado, NO se
  crashea: se devuelve la imagen original y se loggea que el preproceso esta
  ``off`` (con la instruccion de instalacion). El pipeline sigue andando.
- Cada paso esta envuelto en try/except: si una etapa falla (imagen rara, canal
  inesperado), se degrada a la imagen de la etapa previa en vez de romper.

Instalacion (wheels disponibles en Python 3.12-3.14):

    pip install opencv-python-headless pillow numpy
"""

from __future__ import annotations

import importlib.util
import io
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "Preproceso OCR desactivado: falta OpenCV. Instalar "
    "`pip install opencv-python-headless pillow numpy` para deskew/CLAHE/denoise/"
    "binarizacion/upscale (mejora notable en recibos termicos e inclinados)."
)

# Umbral (lado menor en px) por debajo del cual se hace upscale ×2 (recibos
# fotografiados de baja resolucion: el OCR mejora con texto mas grande).
_UPSCALE_MIN_SIDE = 1000
# Lado menor maximo tras upscale (evita imagenes gigantes que ralentizan el OCR).
_UPSCALE_MAX_SIDE = 2200


@dataclass
class PreprocessConfig:
    """Configuracion de las etapas del preproceso.

    Args:
        deskew: Corregir la inclinacion del documento.
        clahe: Aplicar CLAHE (contraste adaptativo; rescata termicos).
        denoise: Aplicar reduccion de ruido.
        binarize: Binarizar (Otsu) para texto negro sobre blanco.
        upscale: Hacer upscale ×2 si la imagen es chica.
    """

    deskew: bool = True
    clahe: bool = True
    denoise: bool = True
    binarize: bool = True
    upscale: bool = True


def opencv_available() -> bool:
    """``True`` si ``cv2`` y ``numpy`` se pueden importar (sin crashear).

    Returns:
        ``True`` si el preproceso real puede correr; ``False`` si falta alguna
        dependencia (en cuyo caso ``preprocess_image`` devuelve el original).
    """
    try:
        return (
            importlib.util.find_spec("cv2") is not None
            and importlib.util.find_spec("numpy") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def unavailable_reason() -> str | None:
    """Motivo si el preproceso no esta disponible (o ``None`` si lo esta)."""
    return None if opencv_available() else _INSTALL_HINT


def _deskew(gray, np, cv2) -> Any:  # type: ignore[no-untyped-def]
    """Corrige la inclinacion estimando el angulo del texto.

    Usa los pixeles de primer plano (texto, oscuro) para estimar el angulo del
    rectangulo minimo que los contiene y rota la imagen para enderezarla. Si el
    angulo estimado es despreciable o absurdo (>45deg de error de estimacion),
    no rota.

    Args:
        gray: Imagen en escala de grises (``np.ndarray`` 2D).
        np: Modulo numpy.
        cv2: Modulo cv2.

    Returns:
        Imagen enderezada (o la original si no aplica/falla).
    """
    try:
        # Texto oscuro -> invertir para que el primer plano sea blanco.
        inverted = cv2.bitwise_not(gray)
        thresh = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))
        if coords.shape[0] < 50:
            return gray  # muy poco texto para estimar angulo con confianza.
        angle = cv2.minAreaRect(coords)[-1]
        # minAreaRect devuelve [-90, 0); normalizar al rango [-45, 45].
        if angle < -45:
            angle = 90 + angle
        if abs(angle) < 0.3 or abs(angle) > 45:
            return gray  # despreciable o ruidoso.
        h, w = gray.shape[:2]
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        return cv2.warpAffine(
            gray, matrix, (w, h),
            flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
        )
    except Exception as exc:  # noqa: BLE001 — degradar sin romper el pipeline.
        logger.debug("deskew fallo, se omite: %s", exc)
        return gray


def _clahe(gray, cv2) -> Any:  # type: ignore[no-untyped-def]
    """Realza el contraste local (CLAHE) — rescata termicos desvanecidos.

    Args:
        gray: Imagen en escala de grises.
        cv2: Modulo cv2.

    Returns:
        Imagen con contraste realzado (o la original si falla).
    """
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray)
    except Exception as exc:  # noqa: BLE001
        logger.debug("CLAHE fallo, se omite: %s", exc)
        return gray


def _denoise(gray, cv2) -> Any:  # type: ignore[no-untyped-def]
    """Reduce ruido conservando bordes del texto (filtro bilateral).

    Args:
        gray: Imagen en escala de grises.
        cv2: Modulo cv2.

    Returns:
        Imagen filtrada (o la original si falla).
    """
    try:
        return cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
    except Exception as exc:  # noqa: BLE001
        logger.debug("denoise fallo, se omite: %s", exc)
        return gray


def _binarize(gray, cv2) -> Any:  # type: ignore[no-untyped-def]
    """Binariza (Otsu) para texto negro neto sobre fondo blanco.

    Args:
        gray: Imagen en escala de grises.
        cv2: Modulo cv2.

    Returns:
        Imagen binaria (o la original si falla).
    """
    try:
        return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    except Exception as exc:  # noqa: BLE001
        logger.debug("binarizacion fallo, se omite: %s", exc)
        return gray


def _maybe_upscale(gray, cv2) -> Any:  # type: ignore[no-untyped-def]
    """Hace upscale ×2 si la imagen es chica (texto mas legible para el OCR).

    Args:
        gray: Imagen en escala de grises.
        cv2: Modulo cv2.

    Returns:
        Imagen ampliada si el lado menor < umbral; si no, la original.
    """
    try:
        h, w = gray.shape[:2]
        min_side = min(h, w)
        if min_side >= _UPSCALE_MIN_SIDE:
            return gray
        scale = 2.0
        if min_side * scale > _UPSCALE_MAX_SIDE:
            scale = _UPSCALE_MAX_SIDE / min_side
        if scale <= 1.05:
            return gray
        return cv2.resize(
            gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("upscale fallo, se omite: %s", exc)
        return gray


def preprocess_image(
    image_bytes: bytes, config: PreprocessConfig | None = None
) -> bytes:
    """Mejora una imagen de recibo para maximizar la precision del OCR.

    Aplica (en orden) deskew, CLAHE, denoise, binarizacion adaptativa y upscale
    condicional. Si OpenCV no esta instalado, **devuelve la imagen original** y
    loggea el motivo (no crashea). Cada etapa degrada con gracia ante errores.

    Args:
        image_bytes: Bytes de la imagen original (JPEG/PNG/...).
        config: Etapas a aplicar. Si es ``None`` se aplican todas.

    Returns:
        Bytes de la imagen mejorada (PNG) si el preproceso corrio; los bytes
        originales si OpenCV falta o la decodificacion falla.
    """
    if not image_bytes:
        return image_bytes

    if not opencv_available():
        logger.info(_INSTALL_HINT)
        return image_bytes

    cfg = config or PreprocessConfig()

    try:
        import cv2
        import numpy as np
    except Exception as exc:  # noqa: BLE001 — import lazy, degradar sin romper.
        logger.warning("No se pudo importar OpenCV/numpy: %s", exc)
        return image_bytes

    try:
        buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        gray = cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            logger.info("Preproceso: imagen no decodificable, se usa el original.")
            return image_bytes

        if cfg.deskew:
            gray = _deskew(gray, np, cv2)
        if cfg.clahe:
            gray = _clahe(gray, cv2)
        if cfg.denoise:
            gray = _denoise(gray, cv2)
        if cfg.upscale:
            gray = _maybe_upscale(gray, cv2)
        if cfg.binarize:
            gray = _binarize(gray, cv2)

        ok, encoded = cv2.imencode(".png", gray)
        if not ok:
            logger.info("Preproceso: re-encode fallo, se usa el original.")
            return image_bytes
        return io.BytesIO(encoded.tobytes()).getvalue()
    except Exception as exc:  # noqa: BLE001 — nunca tumbar el pipeline por preproceso.
        logger.warning("Preproceso fallo por completo, se usa el original: %s", exc)
        return image_bytes
