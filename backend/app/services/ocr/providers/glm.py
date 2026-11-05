"""Proveedor OCR GLM-OCR (Z.AI) — API cloud (el dato SALE del equipo).

GLM-OCR (Z.AI, 0.9B) es el hallazgo 2026 del research §1: #1 en OmniDocBench y
94.5 en Receipt-KIE (supera a GPT-5.2). Modelo open; el owner ya tiene
``ZAI_API_KEY``.

Este provider es la **variante CLOUD** (API Z.AI): el recibo SALE del equipo y se
envía a la API de Z.AI, por eso ``sends_data_externally`` es SIEMPRE ``True`` y el
badge de privacidad debe ser ámbar ("外部に送信"). Requiere consentimiento del
usuario (`allow_external_ocr`).

> Para OCR **local** (datos que NO salen del equipo, gratis, badge verde) existe
> un provider dedicado: `ollama.py` (`OllamaOCRProvider`). NO confundir: este
> provider NUNCA es local — si no hay API key, simplemente no está disponible.

Usa **structured output** (mismo schema que Gemini, fuente única en
`structured.py`): el LLM PROPONE, `parse_receipt` + validación aritmética
VERIFICAN.

Configuracion (settings / env):
    OCR_GLM_ENABLED=true
    OCR_GLM_API_KEY=<zai-key>      # o reutiliza ZAI_API_KEY del entorno
    OCR_GLM_API_URL=https://api.z.ai/api/paas/v4/chat/completions   # opcional
    OCR_GLM_MODEL=glm-ocr          # opcional
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from app.services.ocr.base import (
    OCRProvider,
    OCRProviderUnavailableError,
    OcrRawResult,
)
from app.services.ocr.structured import (
    PROMPT_INSTRUCTIONS,
    parse_structured_response,
    structured_to_raw_result,
)

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "GLM-OCR (Z.AI) no esta configurado. Definir OCR_GLM_API_KEY (o reutilizar "
    "ZAI_API_KEY del entorno). Es un proveedor CLOUD: el recibo sale del equipo "
    "y requiere consentimiento. Para OCR local y gratuito, usar el proveedor "
    "'ollama' (datos NO salen del equipo)."
)

_DEFAULT_ZAI_URL = "https://api.z.ai/api/paas/v4/chat/completions"
_HTTP_TIMEOUT = 60


def _validate_https_url(url: str) -> tuple[str, str | None]:
    """Normaliza y valida el endpoint cloud para evitar esquemas no HTTP."""
    normalized = url.rstrip("/")
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        return normalized, "OCR_GLM_API_URL debe ser una URL HTTPS válida."
    return normalized, None


class GLMOCRProvider(OCRProvider):
    """GLM-OCR (Z.AI) cloud con structured output. El dato SALE del equipo.

    Args:
        api_key: API key de Z.AI. Sin ella el provider no está disponible (este
            provider es exclusivamente cloud; el modo local lo cubre `ollama`).
        api_url: Endpoint de la API Z.AI (chat completions OpenAI-compatible).
        model: Nombre del modelo GLM-OCR.
    """

    name = "glm"
    #: Cloud por definición: el recibo SIEMPRE sale del equipo hacia la API Z.AI.
    sends_data_externally = True

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        ollama_url: str | None = None,  # noqa: ARG002 — compat firma del registry
        model: str = "glm-ocr",
    ) -> None:
        self._api_key = api_key
        self._api_url, self._config_error = _validate_https_url(api_url or _DEFAULT_ZAI_URL)
        self._model = model

    def is_available(self) -> bool:
        """Disponible solo si hay API key de Z.AI (modo cloud).

        Returns:
            ``True`` si hay API key configurada.
        """
        return bool(self._api_key) and self._config_error is None

    def unavailable_reason(self) -> str | None:
        """Instrucciones si falta la API key de Z.AI."""
        if self._config_error is not None:
            return self._config_error
        return None if self.is_available() else _INSTALL_HINT

    def _call_zai(self, image_bytes: bytes, hint: str | None = None) -> str:
        """Llama a la API Z.AI (chat completions OpenAI-compatible).

        Args:
            image_bytes: Bytes de la imagen del recibo (ya preprocesada).
            hint: Pista de post-correccion (error de cuadre) a anexar al prompt.

        Returns:
            El contenido textual del mensaje del modelo (se espera JSON).
        """
        from app.services.ocr.quota import record_usage

        # Modo cloud Z.AI: cuenta la request al free tier (reset diario Pacific).
        record_usage(self.name)

        b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = PROMPT_INSTRUCTIONS if not hint else f"{PROMPT_INSTRUCTIONS}\n\n{hint}"
        payload = {
            "model": self._model,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                }
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._api_url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        # URL scheme was validated in __init__.
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # nosec B310
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "") or ""

    def extract(self, image_bytes: bytes) -> OcrRawResult:
        """Pide a GLM-OCR (Z.AI) el recibo en JSON estructurado y lo normaliza.

        Args:
            image_bytes: Bytes de la imagen del recibo.

        Returns:
            `OcrRawResult` con ``raw_text`` (validacion cruzada) y confianza real.

        Raises:
            OCRProviderUnavailableError: Si no hay API key.
        """
        if not self.is_available():
            raise OCRProviderUnavailableError(self.unavailable_reason() or _INSTALL_HINT)
        return self._run(image_bytes, hint=None)

    def extract_with_hint(self, image_bytes: bytes, hint: str) -> OcrRawResult:
        """Reintento de post-correccion: re-pide el JSON anexando el error de cuadre.

        Args:
            image_bytes: Bytes de la imagen (ya preprocesada).
            hint: Mensaje con el error aritmetico detectado.

        Returns:
            `OcrRawResult` del reintento (mismo procesamiento que `extract`).
        """
        if not self.is_available():
            raise OCRProviderUnavailableError(self.unavailable_reason() or _INSTALL_HINT)
        return self._run(image_bytes, hint=hint)

    def _run(self, image_bytes: bytes, *, hint: str | None) -> OcrRawResult:
        """Ejecuta la llamada a Z.AI y normaliza la salida.

        Args:
            image_bytes: Bytes de la imagen (ya preprocesada).
            hint: Pista de post-correccion, o ``None``.

        Returns:
            `OcrRawResult` con ``raw_text`` y confianza real.
        """
        text = self._call_zai(image_bytes, hint)
        receipt = parse_structured_response(text)
        if receipt is None:
            logger.warning("GLM-OCR no devolvio JSON valido; se usa el texto crudo.")
            return OcrRawResult(
                raw_text=text,
                blocks=[],
                provider=self.name,
                overall_confidence=0.5 if text.strip() else 0.0,
            )
        return structured_to_raw_result(receipt, provider_name=self.name)
