"""Salida estructurada (structured output) compartida por los providers LLM.

El research §5.2 marca el structured output como el segundo paso de mayor impacto:
en vez de pedirle al LLM "transcribi el texto" (texto plano que despues parseamos
con regex), le pedimos un **JSON tipado** con el schema del recibo. El LLM
**propone** la estructura; nuestros parsers + la validacion aritmetica del
pipeline **verifican** (arbitro anti-alucinacion).

Este modulo es la **fuente unica** del:

- Schema Pydantic (`ReceiptStructured`) — el contrato de salida del LLM.
- El JSON-Schema para la API (Gemini/GLM ``response_schema``).
- El prompt few-shot japones (doble tasa 8/10%, インボイス con 登録番号 T+13) con
  instrucciones anti-alucinacion ("null si no se lee, NO inventar; texto literal
  de respaldo").
- El parseo robusto de la respuesta (tolera ```json ... ``` y JSON con ruido).
- La derivacion de **confianza real** (no 0.9 fijo): penaliza por
  ``low_confidence_notes`` y por campos criticos en ``null``.
- La conversion a `OcrRawResult` (con ``raw_text`` para que `parse_receipt` valide
  de forma cruzada y el pipeline siga siendo agnostico del provider).

No hace I/O ni llama a ningun SDK: es logica pura, testeable sin API keys.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.services.ocr.base import OcrBlock, OcrRawResult

logger = logging.getLogger(__name__)


class TaxLineStructured(BaseModel):
    """Linea de区分経理 por tasa propuesta por el LLM.

    Args:
        rate: Tasa de consumo (10 u 8). ``null`` si no se lee.
        base: Importe 税抜 (base imponible) en yenes, o ``null``.
        tax: Importe del 消費税 de ese grupo en yenes, o ``null``.
    """

    rate: int | None = Field(default=None, description="消費税率: 10 u 8")
    base: int | None = Field(default=None, description="税抜 (base imponible) en yenes")
    tax: int | None = Field(default=None, description="消費税額 en yenes")


class ReceiptStructured(BaseModel):
    """Recibo japones propuesto por el LLM en formato estructurado.

    El LLM rellena estos campos leyendo la imagen. Las instrucciones del prompt
    fuerzan ``null`` cuando un dato no se puede leer con certeza (anti-alucinacion)
    y exigen el texto literal de respaldo en ``raw_text``.

    Args:
        date: Fecha del recibo en ISO ``YYYY-MM-DD`` (convertida de 令和/etc por el
            LLM), o ``null`` si no se lee.
        vendor: Nombre del 取引先/店名, o ``null``.
        total: Importe total 税込 en yenes (entero), o ``null``.
        tax_lines: Lineas por tasa (8% / 10%).
        registration_number: 登録番号 ``T`` + 13 digitos, o ``null``.
        raw_text: Transcripcion literal completa del recibo (respaldo para el
            parser de dominio y la auditoria 電帳法).
        low_confidence_notes: Notas del LLM sobre campos dudosos / ilegibles.
    """

    date: str | None = Field(default=None, description="ISO YYYY-MM-DD o null")
    vendor: str | None = Field(default=None, description="店名/取引先 o null")
    total: int | None = Field(default=None, description="合計 税込 en yenes o null")
    tax_lines: list[TaxLineStructured] = Field(default_factory=list)
    registration_number: str | None = Field(
        default=None, description="登録番号 T+13 digitos o null"
    )
    raw_text: str = Field(default="", description="Transcripcion literal de respaldo")
    low_confidence_notes: list[str] = Field(default_factory=list)


# JSON-Schema para la config de structured output de la API (Gemini/GLM).
# Se deriva del modelo Pydantic para mantener una sola fuente de verdad.
RESPONSE_JSON_SCHEMA: dict[str, Any] = ReceiptStructured.model_json_schema()


# Few-shot japones: 2 ejemplos (doble tasa 8/10% con 登録番号; recibo sin 登録番号)
# con su JSON esperado. Anti-alucinacion explicita.
PROMPT_INSTRUCTIONS = (
    "Eres un extractor de datos de recibos japoneses (領収書/レシート) para "
    "contabilidad de 確定申告. Devuelve EXCLUSIVAMENTE un objeto JSON con este "
    "esquema:\n"
    '{"date": "YYYY-MM-DD|null", "vendor": "string|null", "total": int|null, '
    '"tax_lines": [{"rate": 10|8|null, "base": int|null, "tax": int|null}], '
    '"registration_number": "T+13digitos|null", "raw_text": "string", '
    '"low_confidence_notes": ["string"]}\n\n'
    "REGLAS CRITICAS (anti-alucinacion):\n"
    "- Si NO podes leer un digito o campo con certeza, devolve null. NUNCA "
    "inventes ni completes numeros.\n"
    "- Por cada campo dudoso o ilegible, agrega una nota en low_confidence_notes "
    "(ej. 'total borroso, posible 1080 u 1086').\n"
    "- En raw_text incluí SIEMPRE la transcripcion literal completa, linea por "
    "linea, tal cual aparece (¥, %, 円, 登録番号, fechas sin convertir).\n"
    "- date: convertí 令和/平成 a gregoriano ISO (令和6年5月3日 -> 2024-05-03). "
    "令和N = 2018+N.\n"
    "- total: el 合計 税込 en yenes, entero sin comas ni simbolos.\n"
    "- tax_lines: separá 8% (軽減税率) y 10%. base = 税抜, tax = 消費税額 de ese grupo.\n"
    "- registration_number: el 登録番号 インボイス: 'T' + 13 digitos. null si no aparece.\n\n"
    "EJEMPLO 1 (doble tasa, インボイス con 登録番号):\n"
    "Recibo: 'スーパーA / 登録番号 T9234567890123 / 令和6年5月3日 / 内8%対象 348円 "
    "内消費税(8%) 25円 / 内10%対象 520円 内消費税(10%) 47円 / 合計(税込) 868円'\n"
    "JSON: {\"date\": \"2024-05-03\", \"vendor\": \"スーパーA\", \"total\": 868, "
    "\"tax_lines\": [{\"rate\": 10, \"base\": 473, \"tax\": 47}, "
    "{\"rate\": 8, \"base\": 323, \"tax\": 25}], "
    "\"registration_number\": \"T9234567890123\", "
    "\"raw_text\": \"スーパーA\\n登録番号 T9234567890123\\n令和6年5月3日\\n...\", "
    "\"low_confidence_notes\": []}\n\n"
    "EJEMPLO 2 (una sola tasa, sin 登録番号, total legible):\n"
    "Recibo: 'カフェB / 2025/12/01 / コーヒー 500円 / 消費税(10%) 45円 / 合計 495円'\n"
    "JSON: {\"date\": \"2025-12-01\", \"vendor\": \"カフェB\", \"total\": 495, "
    "\"tax_lines\": [{\"rate\": 10, \"base\": 450, \"tax\": 45}], "
    "\"registration_number\": null, "
    "\"raw_text\": \"カフェB\\n2025/12/01\\nコーヒー 500円\\n...\", "
    "\"low_confidence_notes\": []}\n\n"
    "Ahora extraé el JSON del siguiente recibo. Devolve SOLO el JSON, sin texto extra."
)


def _strip_code_fence(text: str) -> str:
    """Quita cercas ```json ... ``` y espacios del texto de la respuesta.

    Args:
        text: Texto crudo devuelto por el LLM.

    Returns:
        El cuerpo sin las cercas de codigo Markdown.
    """
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def _coerce_int(value: Any) -> int | None:
    """Coacciona un valor numerico laxo a ``int`` (o ``None``).

    Tolera floats (``1297.0`` -> ``1297``), strings con yenes/comas (``"¥1,297"``
    -> ``1297``) y vacios. Es habitual que los VLM locales chicos devuelvan estos
    formatos en vez del entero limpio que pide el schema.

    Args:
        value: Valor crudo del JSON del LLM.

    Returns:
        El entero equivalente, o ``None`` si no se puede interpretar.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d-]", "", value)
        if digits and digits != "-":
            try:
                return int(digits)
            except ValueError:
                return None
    return None


def _sanitize_data(data: dict[str, Any]) -> dict[str, Any]:
    """Normaliza desviaciones tipicas de los VLM debiles antes de validar.

    Los modelos locales chicos (ej. GLM-OCR 1.1B) suelen devolver el JSON casi
    correcto pero con detalles que romperian la validacion estricta del schema y
    descartarian TODA la respuesta (incluyendo campos escalares buenos como
    ``total``/``date``/``登録番号``). Esta funcion los salva sin inventar datos:

    - ``tax_lines`` con entradas que NO son objetos (ej. strings ``"8%対象 ¥600"``)
      se descartan (el ``raw_text`` literal cubre la re-extraccion por regex).
    - Numeros como float/strings (``1297.0``, ``"¥1,297"``) se coaccionan a int.
    - ``registration_number`` vacio (``""``) se trata como ``null``.

    No altera el ``raw_text`` ni rellena campos ausentes: solo limpia el ruido de
    formato. El arbitro real sigue siendo la validacion aritmetica del pipeline.

    Args:
        data: Dict crudo del JSON parseado del LLM.

    Returns:
        Dict saneado, apto para ``ReceiptStructured.model_validate``.
    """
    clean = dict(data)
    for key in ("total",):
        if key in clean:
            clean[key] = _coerce_int(clean[key])
    reg = clean.get("registration_number")
    if isinstance(reg, str) and not reg.strip():
        clean["registration_number"] = None
    raw_lines = clean.get("tax_lines")
    if isinstance(raw_lines, list):
        sane_lines: list[dict[str, Any]] = []
        for entry in raw_lines:
            if not isinstance(entry, dict):
                # Entrada no-objeto (string suelta): la descartamos; raw_text cubre.
                continue
            sane_lines.append(
                {
                    "rate": _coerce_int(entry.get("rate")),
                    "base": _coerce_int(entry.get("base")),
                    "tax": _coerce_int(entry.get("tax")),
                }
            )
        clean["tax_lines"] = sane_lines
    elif raw_lines is not None and not isinstance(raw_lines, list):
        clean["tax_lines"] = []
    return clean


def parse_structured_response(text: str) -> ReceiptStructured | None:
    """Parsea (robustamente) la respuesta JSON del LLM a `ReceiptStructured`.

    Tolera respuestas con cercas Markdown (```json), texto envolvente, JSON con
    ruido (extrae el primer objeto ``{...}`` balanceado) y desviaciones tipicas de
    los VLM locales chicos (numeros float/string, ``tax_lines`` con strings) via
    `_sanitize_data` — para no descartar campos escalares buenos por un detalle de
    formato. Si nada parsea, devuelve ``None`` (el pipeline degradara o pasara al
    siguiente provider).

    Args:
        text: Texto devuelto por el modelo.

    Returns:
        `ReceiptStructured` validado, o ``None`` si no se pudo parsear.
    """
    if not text or not text.strip():
        return None

    body = _strip_code_fence(text)
    candidates: list[str] = [body]
    # Respaldo: primer objeto JSON balanceado dentro del texto.
    brace = re.search(r"\{.*\}", body, re.DOTALL)
    if brace and brace.group(0) != body:
        candidates.append(brace.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        try:
            return ReceiptStructured.model_validate(_sanitize_data(data))
        except ValidationError as exc:
            logger.debug("structured output invalido contra el schema: %s", exc)
            continue
    logger.warning("No se pudo parsear structured output del LLM.")
    return None


def _structured_to_raw_text(receipt: ReceiptStructured) -> str:
    """Construye un ``raw_text`` para que `parse_receipt` valide de forma cruzada.

    Prefiere el ``raw_text`` literal que devolvio el LLM. Si vino vacio, sintetiza
    un texto canonico desde los campos estructurados para que los parsers de
    dominio (regex) puedan re-extraer y la validacion aritmetica del pipeline
    funcione igual.

    Args:
        receipt: Recibo estructurado del LLM.

    Returns:
        Texto plano apto para `parse_receipt`.
    """
    if receipt.raw_text and receipt.raw_text.strip():
        return receipt.raw_text

    lines: list[str] = []
    if receipt.vendor:
        lines.append(receipt.vendor)
    if receipt.registration_number:
        lines.append(f"登録番号 {receipt.registration_number}")
    if receipt.date:
        lines.append(receipt.date)
    for tl in receipt.tax_lines:
        if tl.rate is None:
            continue
        if tl.base is not None and tl.tax is not None:
            gross = tl.base + tl.tax
            lines.append(f"内{tl.rate}%対象 {gross}円")
            lines.append(f"内消費税({tl.rate}%) {tl.tax}円")
    if receipt.total is not None:
        lines.append(f"合計（税込） {receipt.total}円")
    return "\n".join(lines)


def derive_confidence(receipt: ReceiptStructured) -> float:
    """Deriva una confianza REAL del structured output (no 0.9 fijo).

    El research §5.2 pide confianza derivada en vez de un valor fijo. Penaliza:

    - Cada nota en ``low_confidence_notes`` (el modelo marco algo dudoso): -0.1.
    - Campos criticos en ``null`` (no leibles): -0.15 ``total``, -0.10 ``date``,
      -0.10 ``tax_lines`` vacio.

    Args:
        receipt: Recibo estructurado del LLM.

    Returns:
        Confianza en ``[0.3, 0.95]`` (nunca 1.0: el LLM no es infalible y el
        arbitro real es la validacion aritmetica del pipeline).
    """
    confidence = 0.95
    confidence -= 0.10 * len(receipt.low_confidence_notes)
    if receipt.total is None:
        confidence -= 0.15
    if receipt.date is None:
        confidence -= 0.10
    if not receipt.tax_lines:
        confidence -= 0.10
    return round(max(0.3, min(0.95, confidence)), 4)


def structured_to_raw_result(
    receipt: ReceiptStructured, *, provider_name: str
) -> OcrRawResult:
    """Convierte el `ReceiptStructured` del LLM a `OcrRawResult` del pipeline.

    El ``raw_text`` resultante permite que `parse_receipt` re-valide los campos de
    forma cruzada: el LLM PROPONE estructura, nuestros parsers + validacion
    aritmetica VERIFICAN. La confianza es la derivada (no fija).

    Args:
        receipt: Recibo estructurado del LLM.
        provider_name: Nombre del provider que lo produjo (gemini/glm).

    Returns:
        `OcrRawResult` compatible con el pipeline (raw_text + confianza real).
    """
    raw_text = _structured_to_raw_text(receipt)
    confidence = derive_confidence(receipt)
    blocks = [
        OcrBlock(text=line, bbox=[], confidence=confidence)
        for line in raw_text.splitlines()
        if line.strip()
    ]
    return OcrRawResult(
        raw_text=raw_text,
        blocks=blocks,
        provider=provider_name,
        overall_confidence=confidence,
    )
