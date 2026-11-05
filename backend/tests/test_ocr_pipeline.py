"""Tests del pipeline OCR, clasificador, registry y consentimiento."""

from __future__ import annotations

import datetime

import pytest

from app.core.config import Settings
from app.services.ocr.base import OCRProviderUnavailableError
from app.services.ocr.classifier import get_default_classifier
from app.services.ocr.parsers import parse_receipt
from app.services.ocr.pipeline import process_receipt, validate_receipt
from app.services.ocr.providers.fake import FakeOCRProvider
from app.services.ocr.registry import provider_statuses, resolve_chain

_REF = datetime.date(2026, 1, 1)


# --- Clasificador ---------------------------------------------------------


@pytest.mark.parametrize(
    ("vendor", "expected_code"),
    [
        ("Amazon.co.jp", "502"),
        ("JR東日本", "501"),
        ("ドコモショップ", "505"),
        ("スターバックス", "504"),
    ],
)
def test_classifier_known_vendors(vendor: str, expected_code: str) -> None:
    """Vendors conocidos del seed mapean a su 勘定科目."""
    suggestion = get_default_classifier().suggest(vendor)
    assert suggestion.account_code == expected_code
    assert suggestion.source == "rule"


def test_classifier_unknown_vendor_defaults_to_zappi() -> None:
    """Vendor desconocido cae en 雑費 (599) con baja confianza."""
    suggestion = get_default_classifier().suggest("謎の個人商店XYZ")
    assert suggestion.account_code == "599"
    assert suggestion.source == "default"


# --- Pipeline (recibo sintetico) ------------------------------------------


def test_pipeline_synthetic_receipt_balanced_journal() -> None:
    """El recibo sintetico produce un 仕訳 candidato balanceado y pending."""
    result = process_receipt(b"x", providers=[FakeOCRProvider()], today=_REF)

    assert result.parsed.total == 868
    assert result.parsed.is_qualified_invoice is True
    assert result.status.value == "pending"  # nunca auto-registra
    assert result.confidence_level == "high"
    assert result.validation.errors == []

    debit = sum(ln.amount for ln in result.journal_candidate.lines if ln.side == "debit")
    credit = sum(ln.amount for ln in result.journal_candidate.lines if ln.side == "credit")
    assert debit == credit == 868


def test_pipeline_failed_reconciliation_is_low_and_blocking() -> None:
    """Si base+税 no cuadra con el total, queda pending/low y bloquea."""
    bad = "店X\n令和6年5月3日\n内10%対象 1000円\n内消費税(10%) 91円\n合計（税込） 5000円\n"
    result = process_receipt(b"x", providers=[FakeOCRProvider(text=bad)], today=_REF)

    assert result.validation.arithmetic_ok is False
    assert result.validation.is_blocking is True
    assert result.confidence_level == "low"
    assert any("Cuadre" in e for e in result.validation.errors)


def test_validate_receipt_rejects_invalid_checksum() -> None:
    """Un 登録番号 con checksum invalido marca registration_ok=False."""
    text = "店\n令和6年5月3日\nT0234567890123\n合計（税込） 1000円\n"
    parsed = parse_receipt(FakeOCRProvider(text=text).extract(b""))
    validation = validate_receipt(parsed, today=_REF)
    assert validation.registration_ok is False
    assert validation.is_blocking is True


# --- Fallback chain -------------------------------------------------------


class _BrokenProvider(FakeOCRProvider):
    """Proveedor que siempre falla al extraer (para probar el fallback)."""

    name = "broken"

    def extract(self, image_bytes: bytes):  # type: ignore[override]
        raise RuntimeError("boom")


def test_pipeline_fallback_chain() -> None:
    """Si el primario falla, el pipeline usa el siguiente de la cadena."""
    result = process_receipt(
        b"x", providers=[_BrokenProvider(), FakeOCRProvider()], today=_REF
    )
    assert result.provider_used == "fake"
    assert result.parsed.total == 868


def test_pipeline_no_providers_raises() -> None:
    """Sin proveedores usables se levanta OCRProviderUnavailableError."""
    with pytest.raises(OCRProviderUnavailableError):
        process_receipt(b"x", providers=[], today=_REF)


# --- Registry + consentimiento --------------------------------------------


def test_resolve_chain_blocks_cloud_without_consent(tmp_path) -> None:
    """allow_external_ocr=False excluye proveedores cloud de la cadena."""
    # evidence_dir aislado: asi `apply_overrides` lee un override vacio (no el
    # ocr_settings.json runtime que pudiera tener consentimiento on).
    settings = Settings(
        evidence_dir=str(tmp_path / "data" / "evidence"),
        allow_external_ocr=False,
        ocr_primary="gemini",
        ocr_fallback_chain=["gemini", "azure"],
        ocr_gemini_enabled=True,
        ocr_gemini_api_key="dummy",  # noqa: S106 — valor de test
        ocr_azure_enabled=True,
        ocr_azure_endpoint="https://x",
        ocr_azure_key="dummy",  # noqa: S106 — valor de test
    )
    # Con consentimiento off los cloud se excluyen explicitamente -> cadena vacia.
    chain = resolve_chain(settings)
    assert chain == []


def test_provider_statuses_reports_consent_block(tmp_path) -> None:
    """provider_statuses expone enabled/available/sends_data_externally."""
    settings = Settings(
        evidence_dir=str(tmp_path / "data" / "evidence"),
        allow_external_ocr=False,
    )
    statuses = {s.name: s for s in provider_statuses(settings)}
    assert {"paddle", "azure", "google", "gemini", "fake"} <= set(statuses)
    # Los cloud son external; sin consentimiento no son usable.
    assert statuses["gemini"].sends_data_externally is True
    assert statuses["gemini"].usable is False
    assert statuses["paddle"].sends_data_externally is False


def test_provider_statuses_fake_usable_when_enabled(tmp_path) -> None:
    """El fake (local) es usable si se habilita."""
    settings = Settings(
        evidence_dir=str(tmp_path / "data" / "evidence"),
        ocr_fake_enabled=True,
    )
    statuses = {s.name: s for s in provider_statuses(settings)}
    assert statuses["fake"].available is True
    assert statuses["fake"].usable is True
