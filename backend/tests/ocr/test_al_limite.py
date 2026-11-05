"""Tests de los componentes 'OCR al limite' (sin API keys ni imagenes reales).

Cubre: preprocess (funcionamiento + degradacion), structured output (parseo
robusto, confianza derivada, raw_text para validacion cruzada), provider GLM
(cloud Z.AI, sends_data_externally siempre True), ensemble (voto campo a campo) y la
integracion en el pipeline (preprocess on/off, ensemble opt-in).
"""

from __future__ import annotations

import datetime

import pytest

from app.core.config import Settings
from app.services.ocr import preprocess
from app.services.ocr.ensemble import vote_fields
from app.services.ocr.parsers import parse_receipt
from app.services.ocr.pipeline import process_receipt
from app.services.ocr.providers.fake import FakeOCRProvider
from app.services.ocr.providers.glm import GLMOCRProvider
from app.services.ocr.structured import (
    ReceiptStructured,
    derive_confidence,
    parse_structured_response,
    structured_to_raw_result,
)

_REF = datetime.date(2026, 1, 1)


# --- Preprocess -----------------------------------------------------------


def test_preprocess_empty_returns_empty() -> None:
    """Bytes vacios devuelven bytes vacios (no crashea)."""
    assert preprocess.preprocess_image(b"") == b""


def test_preprocess_invalid_image_degrades() -> None:
    """Una imagen no decodificable devuelve el original (sin romper)."""
    junk = b"not-an-image-at-all"
    out = preprocess.preprocess_image(junk)
    # Si OpenCV esta: imagen no decodificable -> devuelve el original.
    # Si OpenCV falta: tambien devuelve el original. En ambos casos: no crashea.
    assert out == junk


@pytest.mark.skipif(
    not preprocess.opencv_available(), reason="OpenCV no instalado en este entorno."
)
def test_preprocess_real_image_returns_png() -> None:
    """Con OpenCV, una imagen valida vuelve mejorada y re-encodeada a PNG."""
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    img = np.full((120, 400), 255, dtype=np.uint8)
    cv2.putText(img, "1080 yen", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,), 2)
    ok, encoded = cv2.imencode(".png", img)
    assert ok
    out = preprocess.preprocess_image(encoded.tobytes())
    assert out[:4] == b"\x89PNG"  # PNG magic.
    assert len(out) > 0


def test_preprocess_unavailable_reason_consistent() -> None:
    """`unavailable_reason` es None si OpenCV esta, str si falta."""
    reason = preprocess.unavailable_reason()
    if preprocess.opencv_available():
        assert reason is None
    else:
        assert reason and "OpenCV" in reason


# --- Structured output ----------------------------------------------------


def test_parse_structured_plain_json() -> None:
    """Parsea un JSON plano del LLM al schema `ReceiptStructured`."""
    text = (
        '{"date": "2025-05-03", "vendor": "店A", "total": 868, '
        '"tax_lines": [{"rate": 10, "base": 473, "tax": 47}], '
        '"registration_number": "T9234567890123", "raw_text": "店A...", '
        '"low_confidence_notes": []}'
    )
    receipt = parse_structured_response(text)
    assert receipt is not None
    assert receipt.total == 868
    assert receipt.registration_number == "T9234567890123"
    assert receipt.tax_lines[0].rate == 10


def test_parse_structured_with_code_fence() -> None:
    """Tolera respuestas envueltas en ```json ... ``` (markdown)."""
    text = '```json\n{"date": null, "vendor": "X", "total": 100}\n```'
    receipt = parse_structured_response(text)
    assert receipt is not None
    assert receipt.vendor == "X"
    assert receipt.date is None


def test_parse_structured_with_surrounding_text() -> None:
    """Extrae el primer objeto JSON aunque venga con texto envolvente."""
    text = 'Claro, aqui esta: {"vendor": "Y", "total": 50} -- listo.'
    receipt = parse_structured_response(text)
    assert receipt is not None
    assert receipt.total == 50


def test_parse_structured_garbage_returns_none() -> None:
    """Texto sin JSON devuelve None (el pipeline degradara)."""
    assert parse_structured_response("no hay json aca") is None
    assert parse_structured_response("") is None


def test_derive_confidence_penalizes_notes_and_nulls() -> None:
    """La confianza derivada baja con notas dudosas y campos criticos null."""
    clean = ReceiptStructured(
        date="2025-01-01", vendor="A", total=100,
        tax_lines=[{"rate": 10, "base": 91, "tax": 9}],
    )
    noisy = ReceiptStructured(
        date=None, vendor="A", total=None, tax_lines=[],
        low_confidence_notes=["total borroso", "fecha ilegible"],
    )
    assert derive_confidence(clean) > derive_confidence(noisy)
    assert derive_confidence(noisy) >= 0.3  # piso.
    assert derive_confidence(clean) <= 0.95  # nunca 1.0 (el arbitro es el cuadre).


def test_structured_to_raw_result_enables_cross_validation() -> None:
    """El raw_text del structured permite que parse_receipt re-valide cruzado."""
    receipt = ReceiptStructured(
        date="2024-05-03", vendor="スーパーA", total=868,
        registration_number="T9234567890123",
        tax_lines=[
            {"rate": 10, "base": 473, "tax": 47},
            {"rate": 8, "base": 323, "tax": 25},
        ],
        raw_text="",  # forzar sintesis desde campos.
    )
    raw = structured_to_raw_result(receipt, provider_name="gemini")
    assert raw.provider == "gemini"
    parsed = parse_receipt(raw)
    # Los parsers de dominio re-extraen del raw_text sintetizado.
    assert parsed.total == 868
    assert parsed.is_qualified_invoice is True


# --- GLM provider ---------------------------------------------------------


def test_glm_is_cloud_always_external() -> None:
    """GLM-OCR (Z.AI) es CLOUD: sends_data_externally es SIEMPRE True.

    El badge de privacidad debe ser ámbar ("外部に送信") tenga o no API key: el
    provider nunca opera en local (el modo local lo cubre `OllamaOCRProvider`).
    """
    api_mode = GLMOCRProvider(api_key="secret")  # noqa: S106 — valor de test
    assert api_mode.sends_data_externally is True
    assert api_mode.is_available() is True

    no_key = GLMOCRProvider(api_key=None)
    # Sin key sigue siendo cloud (external), pero NO disponible.
    assert no_key.sends_data_externally is True


def test_glm_unavailable_when_no_key() -> None:
    """Sin API key de Z.AI el provider cloud no esta disponible (no cae a local)."""
    p = GLMOCRProvider(api_key=None)
    assert p.is_available() is False
    assert p.unavailable_reason() is not None


def test_glm_rejects_non_https_api_url() -> None:
    """Una URL cloud no-HTTPS queda no disponible antes de llegar a urlopen."""
    p = GLMOCRProvider(api_key="secret", api_url="file:///tmp/receipt")  # noqa: S106
    assert p.is_available() is False
    assert p.unavailable_reason() == "OCR_GLM_API_URL debe ser una URL HTTPS válida."


# --- Ensemble -------------------------------------------------------------


def test_vote_fields_agreement() -> None:
    """Dos parseos identicos coinciden en todos los campos comparables."""
    raw = "店A\n2025年5月3日\n合計（税込） 1000円\n内消費税(10%) 91円\n"
    a = parse_receipt(FakeOCRProvider(text=raw).extract(b""))
    b = parse_receipt(FakeOCRProvider(text=raw).extract(b""))
    consensus = vote_fields(a, b)
    assert consensus.has_disputes is False
    assert consensus.agreement_ratio == 1.0


def test_vote_fields_dispute() -> None:
    """Totales distintos producen una disputa en 'total'."""
    a = parse_receipt(FakeOCRProvider(text="店A\n合計（税込） 1000円\n").extract(b""))
    b = parse_receipt(FakeOCRProvider(text="店A\n合計（税込） 2000円\n").extract(b""))
    consensus = vote_fields(a, b)
    assert consensus.has_disputes is True
    assert "total" in consensus.disputed_fields


# --- Integracion en el pipeline -------------------------------------------


def test_pipeline_preprocess_toggle_does_not_break_fake() -> None:
    """Con preprocess ON, el FakeProvider (que ignora la imagen) sigue andando."""
    settings_on = Settings(ocr_preprocess_enabled=True)
    result = process_receipt(
        b"img", providers=[FakeOCRProvider()], today=_REF, settings=settings_on
    )
    assert result.parsed.total == 868


def test_pipeline_ensemble_marks_disputes_low() -> None:
    """Con ensemble ON y dos providers que discrepan, baja a low + consensus."""

    class _OtherTotal(FakeOCRProvider):
        name = "other"

    bad = "店X\n令和6年5月3日\n内10%対象 1000円\n内消費税(10%) 91円\n合計（税込） 5000円\n"
    other = "店X\n令和6年5月3日\n内10%対象 1000円\n内消費税(10%) 91円\n合計（税込） 9999円\n"
    settings = Settings(ocr_ensemble_enabled=True)
    result = process_receipt(
        b"img",
        providers=[FakeOCRProvider(text=bad), _OtherTotal(text=other)],
        today=_REF,
        settings=settings,
    )
    # El cuadre del primario falla -> ensemble corre el 2do voto.
    assert result.consensus is not None
    assert result.consensus.has_disputes is True
    assert result.confidence_level == "low"


def test_pipeline_ensemble_off_by_default() -> None:
    """Sin ensemble (default), no se corre 2do provider (consensus None)."""
    bad = "店X\n令和6年5月3日\n内10%対象 1000円\n内消費税(10%) 91円\n合計（税込） 5000円\n"
    result = process_receipt(
        b"img",
        providers=[FakeOCRProvider(text=bad)],
        today=_REF,
        settings=Settings(),  # ensemble off por defecto.
    )
    assert result.consensus is None
