"""Contrato comun de los proveedores OCR.

Define la estructura de salida cruda (`OcrRawResult`) que todos los proveedores
deben producir y la interfaz `OCRProvider` (ABC) que cada implementacion cumple.

Principios:
- `is_available()` nunca debe crashear aunque falte la libreria/credencial: si
  el proveedor no puede operar devuelve ``False`` (y `unavailable_reason`
  explica por que, con instrucciones de instalacion/config).
- `sends_data_externally` distingue proveedores locales (datos NO salen del
  equipo) de los cloud (datos salen). El pipeline lo usa para respetar el
  consentimiento del usuario (`allow_external_ocr`).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class OcrBlock:
    """Bloque de texto detectado por el OCR.

    Args:
        text: Texto reconocido del bloque.
        bbox: Caja contenedora ``[x1, y1, x2, y2]`` en pixeles (vacia si el
            proveedor no expone geometria).
        confidence: Confianza del reconocimiento del bloque (0.0-1.0).
    """

    text: str
    bbox: list[float] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class OcrRawResult:
    """Resultado crudo de un proveedor OCR (antes del parsing de dominio).

    Args:
        raw_text: Texto completo concatenado (orden de lectura natural).
        blocks: Bloques individuales con texto, bbox y confianza.
        provider: Nombre del proveedor que produjo el resultado.
        overall_confidence: Confianza global del documento (0.0-1.0).
    """

    raw_text: str
    blocks: list[OcrBlock] = field(default_factory=list)
    provider: str = "unknown"
    overall_confidence: float = 0.0


class OCRProvider(abc.ABC):
    """Interfaz comun de un proveedor OCR.

    Las implementaciones concretas viven en `app.services.ocr.providers`. Todas
    usan imports diferidos (lazy) de su libreria/SDK para que el modulo se
    importe aunque la dependencia no este instalada.
    """

    #: Nombre estable del proveedor (clave de configuracion y de registry).
    name: str = "base"

    #: ``True`` si el proveedor envia el dato fuera del equipo (cloud).
    sends_data_externally: bool = False

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Indica si el proveedor puede operar ahora mismo.

        Debe chequear dependencias/credenciales sin lanzar excepciones: si algo
        falta, devuelve ``False`` (ver `unavailable_reason`).

        Returns:
            ``True`` si `extract` puede ejecutarse, ``False`` en caso contrario.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def extract(self, image_bytes: bytes) -> OcrRawResult:
        """Ejecuta el OCR sobre una imagen.

        Args:
            image_bytes: Bytes de la imagen (o PDF) del recibo.

        Returns:
            `OcrRawResult` con texto, bloques y confianza.

        Raises:
            OCRProviderUnavailableError: Si el proveedor no esta disponible.
        """
        raise NotImplementedError

    def unavailable_reason(self) -> str | None:
        """Explica por que el proveedor no esta disponible (o ``None``).

        Returns:
            Mensaje legible con instrucciones de instalacion/config, o ``None``
            si el proveedor esta disponible.
        """
        if self.is_available():
            return None
        return f"El proveedor '{self.name}' no esta disponible."


class OCRProviderUnavailableError(RuntimeError):
    """Se lanza al intentar `extract` con un proveedor no disponible."""
