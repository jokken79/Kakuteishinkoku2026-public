"""Proveedor OCR cloud: Azure AI Document Intelligence (prebuilt-receipt).

Los datos SALEN del equipo (van a Azure): solo usar con consentimiento del
usuario (`allow_external_ocr=True`). Import diferido del SDK.

Free tier F0: 500 paginas/mes gratis. Requiere endpoint + API key.

Instalacion:

    pip install azure-ai-documentintelligence

Configuracion (settings / env):
    OCR_AZURE_ENABLED=true
    OCR_AZURE_ENDPOINT=https://<recurso>.cognitiveservices.azure.com/
    OCR_AZURE_KEY=<api-key>
"""

from __future__ import annotations

import logging

from app.services.ocr.base import (
    OcrBlock,
    OCRProvider,
    OCRProviderUnavailableError,
    OcrRawResult,
)

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "Azure Document Intelligence no esta configurado. Instalar "
    "`pip install azure-ai-documentintelligence` y definir OCR_AZURE_ENDPOINT y "
    "OCR_AZURE_KEY (free tier F0: 500 pag/mes)."
)


class AzureDocIntelligenceProvider(OCRProvider):
    """Azure Document Intelligence con el modelo ``prebuilt-receipt``.

    Args:
        endpoint: Endpoint del recurso Azure.
        api_key: API key del recurso.
    """

    name = "azure"
    sends_data_externally = True

    def __init__(self, endpoint: str | None = None, api_key: str | None = None) -> None:
        self._endpoint = endpoint
        self._api_key = api_key

    def _sdk_installed(self) -> bool:
        """``True`` si el SDK de Azure DI esta instalado (nunca crashea)."""
        import importlib.util

        try:
            return importlib.util.find_spec("azure.ai.documentintelligence") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def is_available(self) -> bool:
        """Disponible si el SDK esta instalado y hay endpoint + key.

        Returns:
            ``True`` si se puede llamar a Azure DI.
        """
        return bool(self._sdk_installed() and self._endpoint and self._api_key)

    def unavailable_reason(self) -> str | None:
        """Instrucciones si falta SDK o credenciales."""
        return None if self.is_available() else _INSTALL_HINT

    def extract(self, image_bytes: bytes) -> OcrRawResult:
        """Llama a Azure DI (prebuilt-receipt) y normaliza la salida.

        Args:
            image_bytes: Bytes de la imagen/PDF del recibo.

        Returns:
            `OcrRawResult` con texto y confianza.

        Raises:
            OCRProviderUnavailableError: Si el proveedor no esta configurado.
        """
        if not self.is_available():
            raise OCRProviderUnavailableError(_INSTALL_HINT)

        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential

        from app.services.ocr.quota import record_usage

        # Cuenta esta request real al free tier de Azure (reset diario Pacific).
        record_usage(self.name)

        client = DocumentIntelligenceClient(
            endpoint=str(self._endpoint),
            credential=AzureKeyCredential(str(self._api_key)),
        )
        poller = client.begin_analyze_document(
            "prebuilt-receipt", body=image_bytes, content_type="application/octet-stream"
        )
        result = poller.result()

        blocks: list[OcrBlock] = []
        lines: list[str] = []
        confidences: list[float] = []
        for page in getattr(result, "pages", []) or []:
            for line in getattr(page, "lines", []) or []:
                lines.append(line.content)
        for doc in getattr(result, "documents", []) or []:
            conf = getattr(doc, "confidence", None)
            if conf is not None:
                confidences.append(float(conf))

        raw_text = "\n".join(lines) or getattr(result, "content", "") or ""
        overall = sum(confidences) / len(confidences) if confidences else 0.0
        return OcrRawResult(
            raw_text=raw_text,
            blocks=blocks,
            provider=self.name,
            overall_confidence=overall,
        )
