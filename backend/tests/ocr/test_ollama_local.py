"""Tests del provider OCR 100% LOCAL (Ollama).

Dos niveles:

1. **Unit (siempre corre)**: la disponibilidad sin Ollama, ``sends_data_externally``
   y el saneo de structured output (que rescata respuestas casi-validas de VLM
   chicos sin inventar datos). No requiere Ollama ni red.
2. **Real (opt-in)**: corre el pipeline REAL contra Ollama local si
   ``RUN_REAL_OLLAMA=1``. NO entra en la suite normal (requiere el daemon + modelo
   pulleado). NO gasta cuota cloud (el dato no sale del equipo).

Para la prueba real manual:
    RUN_REAL_OLLAMA=1 pytest tests/ocr/test_ollama_local.py -v -s
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.ocr import quota
from app.services.ocr.pipeline import process_receipt
from app.services.ocr.providers.ollama import OllamaOCRProvider
from app.services.ocr.structured import parse_structured_response

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ocr" / "real_test"


# ----------------------- Unit (siempre) ---------------------------------


def test_local_provider_never_sends_data() -> None:
    """El provider local NUNCA envia el dato fuera del equipo."""
    provider = OllamaOCRProvider(model="glm-ocr")
    assert provider.sends_data_externally is False


def test_unavailable_when_ollama_down() -> None:
    """Si Ollama no responde, ``is_available`` es False (sin crashear)."""
    provider = OllamaOCRProvider(ollama_url="http://127.0.0.1:59999", model="glm-ocr")
    assert provider.is_available() is False
    reason = provider.unavailable_reason()
    assert reason is not None and "Ollama" in reason


def test_invalid_ollama_url_is_unavailable() -> None:
    """Un esquema no HTTP queda rechazado sin tocar urlopen."""
    provider = OllamaOCRProvider(ollama_url="file:///tmp/ollama.sock", model="glm-ocr")
    assert provider.is_available() is False
    assert provider.unavailable_reason() == "OCR_OLLAMA_URL debe ser una URL HTTP/HTTPS válida."


def test_sanitizer_rescues_string_tax_lines_and_float_total() -> None:
    """Un structured casi-valido (tax_lines como strings, total float, reg vacio)
    se rescata: NO se descartan los campos escalares buenos.

    Es el modo de fallo tipico del VLM local chico (GLM-OCR 1.1B).
    """
    text = (
        '{"date": "2025-11-15", "vendor": "X", "total": 1297.0, '
        '"tax_lines": ["8%対象 ¥600", "内消費税(8%) ¥48"], '
        '"registration_number": "", "raw_text": "x"}'
    )
    receipt = parse_structured_response(text)
    assert receipt is not None
    assert receipt.total == 1297  # float -> int
    assert receipt.registration_number is None  # "" -> null
    assert receipt.tax_lines == []  # strings sueltas descartadas (raw_text cubre)


def test_sanitizer_coerces_yen_strings_in_tax_lines() -> None:
    """Numeros con ¥/comas en tax_lines se coaccionan a int (sin inventar)."""
    text = (
        '{"date": null, "vendor": null, "total": "¥1,100", '
        '"tax_lines": [{"rate": "10", "base": "1,000", "tax": "100"}], '
        '"registration_number": null, "raw_text": "y"}'
    )
    receipt = parse_structured_response(text)
    assert receipt is not None
    assert receipt.total == 1100
    assert receipt.tax_lines[0].rate == 10
    assert receipt.tax_lines[0].base == 1000
    assert receipt.tax_lines[0].tax == 100


# ----------------------- Real (opt-in) ----------------------------------

pytestmark_real = pytest.mark.skipif(
    os.environ.get("RUN_REAL_OLLAMA") != "1",
    reason="Prueba REAL de Ollama local: set RUN_REAL_OLLAMA=1 (requiere daemon).",
)


@pytestmark_real
def test_real_local_pipeline_extracts_and_no_quota() -> None:
    """El pipeline local real extrae date/登録番号 y NO consume cuota cloud."""
    base = Settings()
    cfg = base.model_copy(
        update={
            "allow_external_ocr": False,
            "ocr_primary": "ollama",
            "ocr_fallback_chain": ["ollama"],
            "ocr_ollama_enabled": True,
            "ocr_preprocess_enabled": True,
            "ocr_postcorrection_enabled": True,
        }
    )
    image = (_FIXTURES / "receipt_03_taxi_invoice.png").read_bytes()

    before = quota.usage_today("ollama")
    result = process_receipt(image, today=datetime.date(2026, 1, 1), settings=cfg)
    after = quota.usage_today("ollama")

    assert result.provider_used == "ollama"
    assert result.parsed.raw_text.strip(), "El modelo local debe devolver texto."
    # El dato no sale del equipo -> NO cuenta cuota cloud.
    assert after == before
    # Campos estables del recibo del taxi (date y 登録番号 son los mas fiables).
    assert result.parsed.date == datetime.date(2025, 10, 28)
    assert result.parsed.registration_number == "T2876543210987"
