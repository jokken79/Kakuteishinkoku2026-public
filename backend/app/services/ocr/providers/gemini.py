"""Proveedor OCR cloud: Gemini Vision-LLM con structured output (datos SALEN).

Vision-LLM de alta precision para japones, gratis para el volumen tipico
(Gemini 3 Flash: ~1.500 req/dia gratis, sin tarjeta). Solo con consentimiento
(`allow_external_ocr=True`). Import diferido del SDK.

A diferencia de la version previa (transcripcion a texto plano), este provider
pide **structured output**: un JSON tipado con el schema del recibo
(`ReceiptStructured`). Usa ``response_schema`` + ``response_mime_type`` de la API
de Gemini si la lib lo soporta; si no, cae a un prompt que fuerza JSON + parseo
robusto. El LLM PROPONE la estructura; `parse_receipt` + la validacion aritmetica
del pipeline VERIFICAN (arbitro anti-alucinacion). La confianza es **derivada**
(no 0.9 fijo): ver `structured.derive_confidence`.

Instalacion:

    pip install google-genai

Configuracion (settings / env):
    OCR_GEMINI_ENABLED=true
    OCR_GEMINI_API_KEY=<api-key>          # gratis en aistudio.google.com
    OCR_GEMINI_MODEL=gemini-3-flash       # opcional (default gemini-3-flash)
"""

from __future__ import annotations

import logging
from typing import Any, cast

from app.services.ocr.base import (
    OCRProvider,
    OCRProviderUnavailableError,
    OcrRawResult,
)
from app.services.ocr.structured import (
    PROMPT_INSTRUCTIONS,
    RESPONSE_JSON_SCHEMA,
    parse_structured_response,
    structured_to_raw_result,
)

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "Gemini Vision no esta configurado. Instalar `pip install google-genai` y "
    "definir OCR_GEMINI_API_KEY (Gemini 3 Flash: ~1.500 req/dia gratis, alta "
    "precision JP). Key gratis en https://aistudio.google.com/apikey ."
)


class GeminiVisionProvider(OCRProvider):
    """Gemini Vision-LLM con structured output para recibos japoneses.

    Args:
        api_key: API key de Gemini.
        model: Nombre del modelo (``gemini-3-flash`` por defecto).
    """

    name = "gemini"
    sends_data_externally = True

    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-flash") -> None:
        self._api_key = api_key
        self._model = model

    def _sdk_installed(self) -> bool:
        """``True`` si el SDK ``google-genai`` esta instalado (nunca crashea)."""
        import importlib.util

        try:
            return importlib.util.find_spec("google.genai") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def is_available(self) -> bool:
        """Disponible si el SDK esta instalado y hay API key.

        Returns:
            ``True`` si se puede llamar a Gemini.
        """
        return bool(self._sdk_installed() and self._api_key)

    def unavailable_reason(self) -> str | None:
        """Instrucciones si falta SDK o API key."""
        return None if self.is_available() else _INSTALL_HINT

    def _call_model(self, image_bytes: bytes, hint: str | None = None) -> str:
        """Llama a Gemini pidiendo JSON estructurado y devuelve el texto crudo.

        Intenta primero con ``response_schema`` + ``response_mime_type`` (modo
        nativo de structured output). Si esa config no esta soportada por la
        version del SDK, cae a un ``generate_content`` simple (el prompt ya fuerza
        JSON) — el parseo posterior es robusto a ambos casos.

        Args:
            image_bytes: Bytes de la imagen del recibo (ya preprocesada).
            hint: Pista de post-correccion (error de cuadre) a anexar al prompt.

        Returns:
            El texto de la respuesta del modelo (se espera JSON).
        """
        from google import genai
        from google.genai import types

        from app.services.ocr.quota import record_usage

        client = genai.Client(api_key=self._api_key)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")
        prompt = PROMPT_INSTRUCTIONS if not hint else f"{PROMPT_INSTRUCTIONS}\n\n{hint}"
        contents = cast(Any, [image_part, prompt])

        # Cuenta esta llamada REAL al free tier (reset diario Pacific). Se hace
        # ANTES de la request porque la cuota se consume al emitirla, aunque la
        # respuesta falle. Los providers locales NO cuentan.
        record_usage(self.name)

        try:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RESPONSE_JSON_SCHEMA,
                temperature=0.0,
            )
            response = client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except Exception as exc:  # noqa: BLE001 — fallback a modo simple.
            logger.info(
                "Gemini structured-config no soportado (%s); fallback a prompt JSON.",
                exc,
            )
            response = client.models.generate_content(
                model=self._model,
                contents=contents,
            )
        return getattr(response, "text", "") or ""

    def extract_with_hint(self, image_bytes: bytes, hint: str) -> OcrRawResult:
        """Reintento de post-correccion: re-pide el JSON anexando el error de cuadre.

        Args:
            image_bytes: Bytes de la imagen (ya preprocesada).
            hint: Mensaje con el error aritmetico detectado.

        Returns:
            `OcrRawResult` del reintento (mismo procesamiento que `extract`).
        """
        text = self._call_model(image_bytes, hint=hint)
        receipt = parse_structured_response(text)
        if receipt is None:
            return OcrRawResult(
                raw_text=text, blocks=[], provider=self.name,
                overall_confidence=0.5 if text.strip() else 0.0,
            )
        return structured_to_raw_result(receipt, provider_name=self.name)

    def extract(self, image_bytes: bytes) -> OcrRawResult:
        """Pide a Gemini el recibo en JSON estructurado y lo normaliza.

        Args:
            image_bytes: Bytes de la imagen del recibo.

        Returns:
            `OcrRawResult` con ``raw_text`` (para validacion cruzada) y confianza
            **derivada** (no fija).

        Raises:
            OCRProviderUnavailableError: Si el proveedor no esta configurado.
        """
        if not self.is_available():
            raise OCRProviderUnavailableError(_INSTALL_HINT)

        text = self._call_model(image_bytes)
        receipt = parse_structured_response(text)
        if receipt is None:
            # El modelo no devolvio JSON parseable: degradar usando el texto crudo
            # como raw_text (parse_receipt aun puede extraer algo por regex).
            logger.warning("Gemini no devolvio JSON valido; se usa el texto crudo.")
            return OcrRawResult(
                raw_text=text,
                blocks=[],
                provider=self.name,
                overall_confidence=0.5 if text.strip() else 0.0,
            )
        return structured_to_raw_result(receipt, provider_name=self.name)
