"""Proveedor OCR 100% LOCAL via Ollama (datos NO salen del equipo, $0).

Usa un VLM (vision LLM) servido por Ollama en ``http://localhost:11434`` para
extraer recibos japoneses SIN que el dato salga del equipo. Es la alternativa
**privada y gratuita** a Gemini (cloud). El modelo recomendado es ``glm-ocr``
(GLM-OCR, 1.1B con capability ``vision``: ``ollama pull glm-ocr``), pero sirve
cualquier VLM de Ollama (``minicpm-v``, ``llama3.2-vision``, ``qwen2.5vl``...).

Diferencia con el provider `glm` (que tiene un modo Ollama heredado): este
provider está pensado **solo para local** y, sobre todo, usa un prompt adaptado a
modelos chicos. El few-shot largo de `structured.PROMPT_INSTRUCTIONS` (pensado
para Gemini) hace que un VLM de ~1B **copie** los valores del ejemplo en vez de
leer la imagen. Acá el prompt es minimal y sin valores concretos copiables: pide
el JSON del schema con reglas, sin ejemplos rellenos.

Como todos los providers LLM: el modelo PROPONE el JSON, y `parse_receipt` + la
validación aritmética del pipeline VERIFICAN (árbitro anti-alucinación). Reusa
`structured.py` (schema, parseo robusto, confianza derivada, conversión a
`OcrRawResult`) — fuente única compartida con Gemini/GLM.

``sends_data_externally`` es SIEMPRE ``False``: el recibo nunca sale del equipo,
y por eso NO consume cuota cloud (no se llama a ``record_usage``).

Configuración (settings / env):
    OCR_OLLAMA_ENABLED=true
    OCR_OLLAMA_URL=http://localhost:11434   # opcional (default)
    OCR_OLLAMA_MODEL=glm-ocr                # opcional (default)
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
    parse_structured_response,
    structured_to_raw_result,
)

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_HTTP_TIMEOUT = 180  # los VLM locales en CPU pueden tardar; margen amplio.

_INSTALL_HINT = (
    "OCR local (Ollama) no está disponible. Instalar Ollama "
    "(https://ollama.com), bajar un modelo de visión con `ollama pull glm-ocr` "
    "(GLM-OCR, ~2.2GB) y dejar el daemon corriendo en "
    "http://localhost:11434 . El dato NUNCA sale del equipo y es gratis ($0)."
)

# Prompt MINIMAL para VLM locales (chicos). A diferencia del few-shot de Gemini,
# NO incluye valores de ejemplo concretos: un modelo de ~1B tiende a copiarlos en
# vez de leer la imagen. Solo schema + reglas anti-alucinación.
_LOCAL_PROMPT = (
    "You are an OCR extractor for a Japanese receipt (領収書/レシート). "
    "Read ONLY the receipt in the image. Output EXACTLY one JSON object, "
    "no prose, no code fences, with these keys:\n"
    '{"date": "YYYY-MM-DD or null", "vendor": "store name or null", '
    '"total": integer yen or null, '
    '"tax_lines": [{"rate": 10 or 8 or null, "base": integer yen 税抜 or null, '
    '"tax": integer yen 消費税 or null}], '
    '"registration_number": "T followed by 13 digits, or null", '
    '"raw_text": "verbatim transcription of every line, exactly as printed", '
    '"low_confidence_notes": ["notes about unreadable fields"]}\n'
    "Rules:\n"
    "- Read the values FROM THE IMAGE. Do NOT invent or copy any example. "
    "If a digit or field is not legible, use null.\n"
    "- date: convert 令和N年 to Gregorian (令和N = 2018+N); else use the printed "
    "Gregorian date. Format YYYY-MM-DD.\n"
    "- total: the 合計/お買上 税込 amount in yen, integer, no commas or symbols.\n"
    "- tax_lines: one entry per tax rate present (8% 軽減税率 and/or 10%). "
    "base = 税抜 amount, tax = 消費税 amount of that group.\n"
    "- registration_number: the インボイス 登録番号 (T + 13 digits) if printed, "
    "else null.\n"
    "- raw_text: copy every visible line of THIS receipt verbatim.\n"
    "Output only the JSON object."
)


def _validate_http_url(url: str) -> tuple[str, str | None]:
    """Normaliza y valida el endpoint de Ollama antes de usar urlopen."""
    normalized = url.rstrip("/")
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return normalized, "OCR_OLLAMA_URL debe ser una URL HTTP/HTTPS válida."
    return normalized, None


class OllamaOCRProvider(OCRProvider):
    """OCR local via Ollama (VLM de visión). Datos NO salen del equipo.

    Args:
        ollama_url: Endpoint de Ollama local (default ``http://localhost:11434``).
        model: Nombre del modelo de visión en Ollama (default ``glm-ocr``).
    """

    name = "ollama"
    sends_data_externally = False

    def __init__(
        self,
        ollama_url: str | None = None,
        model: str = "glm-ocr",
    ) -> None:
        self._ollama_url, self._config_error = _validate_http_url(
            ollama_url or _DEFAULT_OLLAMA_URL
        )
        self._model = model

    def _list_models(self) -> list[str] | None:
        """Lista los modelos presentes en Ollama, o ``None`` si no responde.

        Returns:
            Lista de nombres de modelo (``name``), o ``None`` si el daemon no
            está accesible.
        """
        if self._config_error is not None:
            return None
        try:
            req = urllib.request.Request(
                f"{self._ollama_url}/api/tags", method="GET"
            )
            # URL scheme was validated in __init__.
            with urllib.request.urlopen(req, timeout=2) as resp:  # nosec B310
                if not 200 <= resp.status < 300:
                    return None
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            return None
        models = body.get("models") or []
        return [m.get("name", "") for m in models if isinstance(m, dict)]

    def _model_present(self, available: list[str]) -> bool:
        """``True`` si el modelo configurado está pulleado en Ollama.

        Tolera el sufijo ``:latest`` (``glm-ocr`` == ``glm-ocr:latest``).

        Args:
            available: Nombres de modelos presentes en Ollama.

        Returns:
            ``True`` si el modelo configurado figura entre los disponibles.
        """
        wanted = self._model
        wanted_latest = wanted if ":" in wanted else f"{wanted}:latest"
        for name in available:
            if name == wanted or name == wanted_latest:
                return True
            # ``glm-ocr:latest`` configurado, ``glm-ocr`` presente: aceptar.
            if name.split(":", 1)[0] == wanted.split(":", 1)[0] and (
                wanted.split(":", 1)[0] == wanted or name == wanted_latest
            ):
                return True
        return False

    def is_available(self) -> bool:
        """Disponible si Ollama responde y el modelo de visión está pulleado.

        Returns:
            ``True`` si se puede ejecutar OCR local con el modelo configurado.
        """
        if self._config_error is not None:
            return False
        available = self._list_models()
        if available is None:
            return False
        return self._model_present(available)

    def unavailable_reason(self) -> str | None:
        """Instrucciones si Ollama no responde o falta el modelo."""
        if self._config_error is not None:
            return self._config_error
        if self.is_available():
            return None
        available = self._list_models()
        if available is None:
            return _INSTALL_HINT
        return (
            f"El modelo de visión '{self._model}' no está en Ollama. "
            f"Bajalo con `ollama pull {self._model}`. Modelos presentes: "
            f"{', '.join(available) or '(ninguno)'}."
        )

    def _call_ollama(self, image_bytes: bytes, hint: str | None = None) -> str:
        """Llama a Ollama (``/api/generate``) con la imagen y devuelve el texto.

        El dato NO sale del equipo: por eso NO se llama a ``record_usage`` (no
        consume cuota cloud).

        Args:
            image_bytes: Bytes de la imagen del recibo (ya preprocesada).
            hint: Pista de post-corrección (error de cuadre) a anexar al prompt.

        Returns:
            El texto de la respuesta del modelo (se espera JSON).
        """
        b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = _LOCAL_PROMPT if not hint else f"{_LOCAL_PROMPT}\n\n{hint}"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._ollama_url}/api/generate",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        # URL scheme was validated in __init__.
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # nosec B310
            body = json.loads(resp.read().decode("utf-8"))
        return body.get("response", "") or ""

    def extract(self, image_bytes: bytes) -> OcrRawResult:
        """Pide al VLM local el recibo en JSON estructurado y lo normaliza.

        Args:
            image_bytes: Bytes de la imagen del recibo.

        Returns:
            `OcrRawResult` con ``raw_text`` (validación cruzada) y confianza real.

        Raises:
            OCRProviderUnavailableError: Si Ollama/el modelo no están disponibles.
        """
        if not self.is_available():
            raise OCRProviderUnavailableError(self.unavailable_reason() or _INSTALL_HINT)
        return self._run(image_bytes, hint=None)

    def extract_with_hint(self, image_bytes: bytes, hint: str) -> OcrRawResult:
        """Reintento de post-corrección: re-pide el JSON anexando el error de cuadre.

        Args:
            image_bytes: Bytes de la imagen (ya preprocesada).
            hint: Mensaje con el error aritmético detectado.

        Returns:
            `OcrRawResult` del reintento (mismo procesamiento que `extract`).
        """
        if not self.is_available():
            raise OCRProviderUnavailableError(self.unavailable_reason() or _INSTALL_HINT)
        return self._run(image_bytes, hint=hint)

    def _run(self, image_bytes: bytes, *, hint: str | None) -> OcrRawResult:
        """Ejecuta la llamada local y normaliza la salida (mismo flujo que Gemini).

        Args:
            image_bytes: Bytes de la imagen (ya preprocesada).
            hint: Pista de post-corrección, o ``None``.

        Returns:
            `OcrRawResult` con ``raw_text`` y confianza real.
        """
        text = self._call_ollama(image_bytes, hint)
        receipt = parse_structured_response(text)
        if receipt is None:
            logger.warning("OCR local (Ollama) no devolvió JSON válido; texto crudo.")
            return OcrRawResult(
                raw_text=text,
                blocks=[],
                provider=self.name,
                overall_confidence=0.5 if text.strip() else 0.0,
            )
        return structured_to_raw_result(receipt, provider_name=self.name)
