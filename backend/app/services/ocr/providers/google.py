"""Proveedor OCR cloud: Google Document AI / Vision (datos SALEN del equipo).

Solo con consentimiento (`allow_external_ocr=True`). Import diferido del SDK.

Free tier: ~1000 paginas/mes (varia por procesador). Requiere project_id,
location y un procesador (o credenciales de Vision).

Instalacion:

    pip install google-cloud-documentai

Configuracion (settings / env):
    OCR_GOOGLE_ENABLED=true
    OCR_GOOGLE_PROJECT_ID=<gcp-project>
    OCR_GOOGLE_LOCATION=us            # o 'eu'
    OCR_GOOGLE_PROCESSOR_ID=<processor-id>
    GOOGLE_APPLICATION_CREDENTIALS=<ruta-al-service-account.json>
"""

from __future__ import annotations

import logging

from app.services.ocr.base import (
    OCRProvider,
    OCRProviderUnavailableError,
    OcrRawResult,
)

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "Google Document AI no esta configurado. Instalar "
    "`pip install google-cloud-documentai`, definir OCR_GOOGLE_PROJECT_ID, "
    "OCR_GOOGLE_LOCATION y OCR_GOOGLE_PROCESSOR_ID, y exportar "
    "GOOGLE_APPLICATION_CREDENTIALS (free tier ~1000 pag/mes)."
)


class GoogleDocAIProvider(OCRProvider):
    """Google Document AI (procesador OCR/Receipt).

    Args:
        project_id: ID del proyecto GCP.
        location: Region del procesador (``us``/``eu``).
        processor_id: ID del procesador de Document AI.
    """

    name = "google"
    sends_data_externally = True

    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        processor_id: str | None = None,
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._processor_id = processor_id

    def _sdk_installed(self) -> bool:
        """``True`` si el SDK de Document AI esta instalado (nunca crashea)."""
        import importlib.util

        try:
            return importlib.util.find_spec("google.cloud.documentai") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def is_available(self) -> bool:
        """Disponible si SDK instalado y hay project/location/processor.

        Returns:
            ``True`` si se puede llamar a Document AI.
        """
        return bool(
            self._sdk_installed()
            and self._project_id
            and self._location
            and self._processor_id
        )

    def unavailable_reason(self) -> str | None:
        """Instrucciones si falta SDK o config."""
        return None if self.is_available() else _INSTALL_HINT

    def extract(self, image_bytes: bytes) -> OcrRawResult:
        """Llama a Document AI y normaliza la salida.

        Args:
            image_bytes: Bytes de la imagen/PDF del recibo.

        Returns:
            `OcrRawResult` con el texto reconocido.

        Raises:
            OCRProviderUnavailableError: Si el proveedor no esta configurado.
        """
        if not self.is_available():
            raise OCRProviderUnavailableError(_INSTALL_HINT)

        from google.cloud import documentai

        from app.services.ocr.quota import record_usage

        # Cuenta esta request real al free tier de Document AI (reset Pacific).
        record_usage(self.name)

        client = documentai.DocumentProcessorServiceClient()
        name = client.processor_path(
            str(self._project_id), str(self._location), str(self._processor_id)
        )
        raw_document = documentai.RawDocument(
            content=image_bytes, mime_type="image/jpeg"
        )
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        result = client.process_document(request=request)
        document = result.document

        return OcrRawResult(
            raw_text=document.text or "",
            blocks=[],
            provider=self.name,
            overall_confidence=0.0,
        )
