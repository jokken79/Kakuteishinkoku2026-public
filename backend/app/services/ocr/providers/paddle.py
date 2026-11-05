"""Proveedor OCR local con PaddleOCR PP-OCRv5 (datos NO salen del equipo).

Import diferido (lazy) de ``paddleocr``: el modulo se importa aunque la libreria
no este instalada. `is_available()` devuelve ``False`` con instrucciones si falta.

Instalacion (recomendado en venv Python 3.12/3.13 aparte; PaddlePaddle puede dar
friccion con 3.14):

    pip install paddlepaddle paddleocr

La primera ejecucion descarga los modelos PP-OCRv5 a la cache local (una vez).
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.ocr.base import (
    OcrBlock,
    OCRProvider,
    OCRProviderUnavailableError,
    OcrRawResult,
)

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "PaddleOCR no esta instalado. Instalar en un venv Python 3.12/3.13: "
    "`pip install paddlepaddle paddleocr`. La primera corrida descarga los "
    "modelos PP-OCRv5 a la cache local."
)


class PaddleOCRProvider(OCRProvider):
    """PaddleOCR PP-OCRv5 local (Apache 2.0, japones).

    Args:
        lang: Idioma de los modelos (``"japan"`` por defecto).
    """

    name = "paddle"
    sends_data_externally = False

    def __init__(self, lang: str = "japan") -> None:
        self._lang = lang
        self._engine: Any = None

    def is_available(self) -> bool:
        """Comprueba si ``paddleocr`` esta instalado (sin instanciar modelos).

        Returns:
            ``True`` si la libreria se puede importar, ``False`` si no.
        """
        try:
            import importlib.util

            return importlib.util.find_spec("paddleocr") is not None
        except (ImportError, ValueError):
            return False

    def unavailable_reason(self) -> str | None:
        """Instrucciones de instalacion si el proveedor no esta disponible."""
        return None if self.is_available() else _INSTALL_HINT

    def _get_engine(self) -> Any:
        """Instancia perezosa del motor PaddleOCR (import lazy)."""
        if self._engine is None:
            from paddleocr import PaddleOCR  # import diferido

            self._engine = PaddleOCR(use_angle_cls=True, lang=self._lang)
        return self._engine

    def extract(self, image_bytes: bytes) -> OcrRawResult:
        """Ejecuta PaddleOCR sobre los bytes de la imagen.

        Args:
            image_bytes: Bytes de la imagen del recibo.

        Returns:
            `OcrRawResult` con texto, bloques (bbox+confianza) y confianza global.

        Raises:
            OCRProviderUnavailableError: Si ``paddleocr`` no esta instalado.
        """
        if not self.is_available():
            raise OCRProviderUnavailableError(_INSTALL_HINT)

        import io

        import numpy as np
        from PIL import Image

        engine = self._get_engine()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        result = engine.ocr(np.array(image), cls=True)

        blocks: list[OcrBlock] = []
        lines: list[str] = []
        confidences: list[float] = []
        # PaddleOCR (legacy `.ocr(cls=True)`) devuelve [[ [box, (text, conf)], ... ]]
        # (una pagina). Guardamos por item: si una version del SDK cambia la forma
        # del resultado, saltamos ese item en vez de reventar todo el `extract` con
        # un ValueError de desempaquetado (paddle es el provider primario).
        for page in result or []:
            for item in page or []:
                try:
                    box, (text, conf) = item
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                except (ValueError, TypeError):
                    logger.warning(
                        "PaddleOCR devolvio un item con forma inesperada; se omite."
                    )
                    continue
                blocks.append(
                    OcrBlock(
                        text=text,
                        bbox=[min(xs), min(ys), max(xs), max(ys)],
                        confidence=float(conf),
                    )
                )
                lines.append(text)
                confidences.append(float(conf))

        overall = sum(confidences) / len(confidences) if confidences else 0.0
        return OcrRawResult(
            raw_text="\n".join(lines),
            blocks=blocks,
            provider=self.name,
            overall_confidence=overall,
        )
