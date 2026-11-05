"""Prueba REAL del OCR Gemini (opt-in, gasta free tier).

Este test llama a la API REAL de Gemini con la key del .env. Por eso es OPT-IN:
solo corre si ``RUN_REAL_GEMINI=1`` esta en el entorno (asi NO entra en la suite
normal ni gasta cuota en CI/local por accidente). Verifica que:

- El provider gemini levanta ``is_available()`` con la key.
- El pipeline real extrae date/total/登録番号 de un recibo generado.
- El contador de cuota incrementa tras la llamada real.

Para correrlo manualmente:
    RUN_REAL_GEMINI=1 pytest tests/ocr/test_real_gemini.py -v -s
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.ocr import quota
from app.services.ocr.pipeline import process_receipt
from app.services.ocr.providers.gemini import GeminiVisionProvider

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ocr" / "real_test"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_GEMINI") != "1",
    reason="Prueba REAL de Gemini (gasta free tier): set RUN_REAL_GEMINI=1 para correr.",
)


def _real_settings() -> Settings:
    """Settings con gemini real activo (limite alto para no frenar la prueba).

    Nota: NO se aisla ``evidence_dir`` porque el provider cuenta la cuota via
    ``get_settings()`` (default), no via estas settings inyectadas. Para que el
    test observe el mismo contador que el provider escribe, ambos usan el path
    por defecto. El incremento es real (gasta free tier).
    """
    base = Settings()
    return base.model_copy(
        update={
            "allow_external_ocr": True,
            "ocr_primary": "gemini",
            "ocr_fallback_chain": ["gemini"],
            "ocr_gemini_enabled": True,
            "ocr_preprocess_enabled": True,
            "ocr_gemini_daily_limit": 100000,
        }
    )


def test_gemini_is_available_with_real_key() -> None:
    """El provider gemini levanta is_available con la key del .env."""
    cfg = Settings()
    provider = GeminiVisionProvider(api_key=cfg.ocr_gemini_api_key, model=cfg.ocr_gemini_model)
    assert provider.is_available() is True, "Falta la API key o el SDK google-genai."


def test_real_pipeline_extracts_and_counts_quota() -> None:
    """El pipeline real extrae campos clave y la cuota incrementa."""
    cfg = _real_settings()
    image = (_FIXTURES / "receipt_03_taxi_invoice.png").read_bytes()

    # El provider cuenta via get_settings() (default), por eso leemos ahi.
    before = quota.usage_today("gemini")
    result = process_receipt(image, today=datetime.date(2026, 1, 1), settings=cfg)
    after = quota.usage_today("gemini")

    # Plumbing (lo determinista): provider real, cuota incrementada, JSON valido.
    assert result.provider_used == "gemini"
    assert after > before, "El provider cloud debe incrementar el contador de cuota."
    assert result.parsed.raw_text.strip(), "Gemini debe devolver texto."
    # Campos estables del recibo del taxi (Gemini es muy fiable en fecha y 登録番号;
    # el total puede variar ocasionalmente, por eso no se asevera de forma dura).
    assert result.parsed.date == datetime.date(2025, 10, 28)
    assert result.parsed.registration_number == "T2876543210987"
    assert result.parsed.is_qualified_invoice is True
