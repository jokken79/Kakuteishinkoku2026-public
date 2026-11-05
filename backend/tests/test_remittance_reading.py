"""Lectura temporal de documentos bancarios con datos ficticios."""

import io
import sys

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services import remittance_reading
from app.services.ocr.base import OcrRawResult
from app.services.remittance_reading import RemittanceReadingError, read_remittance


def test_pdf_text_extracted_without_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Example bank transfer to Maria 12345")
    data = document.tobytes()
    document.close()
    monkeypatch.setattr(remittance_reading, "_local_ocr", lambda *_: pytest.fail("OCR innecesario"))
    result = read_remittance(data)
    assert "Example bank transfer to Maria 12345" in result["text"]
    assert result["warnings"] == []


def test_short_pdf_text_is_preserved_when_ocr_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Maria")
    data = document.tobytes()
    document.close()
    monkeypatch.setattr(remittance_reading.PaddleOCRProvider, "is_available", lambda _: False)
    monkeypatch.setattr(remittance_reading, "_windows_ocr", lambda *_: None)
    result = read_remittance(data)
    assert "Maria" in result["text"]
    assert "ocr_unavailable" in result["warnings"]


def test_pdf_with_text_header_and_scanned_receipt_uses_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = io.BytesIO()
    Image.new("RGB", (300, 300), "white").save(image, format="PNG")
    document = pymupdf.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((30, 30), "Bank transfer header with selectable text")
    page.insert_image(pymupdf.Rect(20, 80, 380, 440), stream=image.getvalue())
    data = document.tobytes()
    document.close()
    calls: list[bytes] = []

    def fake_ocr(image_bytes: bytes, _warnings: list[str], _language: str) -> str:
        calls.append(image_bytes)
        return "Scanned transfer amount 12345"

    monkeypatch.setattr(remittance_reading, "_local_ocr", fake_ocr)
    result = read_remittance(data)
    assert len(calls) == 1
    assert "Bank transfer header" in result["text"]
    assert "Scanned transfer amount 12345" in result["text"]
    assert "puede repetir texto" in result["text"]


def test_missing_page_is_reported_even_when_another_page_has_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Example bank transfer with enough text")
    document.new_page()
    data = document.tobytes()
    document.close()
    monkeypatch.setattr(remittance_reading, "_local_ocr", lambda *_: "")
    result = read_remittance(data)
    assert result["empty_pages"] == [2]
    assert "Example bank transfer" in result["text"]


def test_image_uses_local_ocr_and_no_provider_means_explicit_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="PNG")
    monkeypatch.setattr(remittance_reading.PaddleOCRProvider, "is_available", lambda _: True)
    monkeypatch.setattr(
        remittance_reading.PaddleOCRProvider,
        "extract",
        lambda _self, _image: OcrRawResult(raw_text="Transferencia de ejemplo"),
    )
    assert "Transferencia de ejemplo" in read_remittance(buf.getvalue())["text"]
    monkeypatch.setattr(remittance_reading.PaddleOCRProvider, "is_available", lambda _: False)
    monkeypatch.setattr(remittance_reading, "_windows_ocr", lambda *_: None)
    assert read_remittance(buf.getvalue())["warnings"] == ["ocr_unavailable", "no_text"]


@pytest.mark.skipif(sys.platform != "win32", reason="Reconocedor de Windows")
def test_windows_local_ocr_reads_fictitious_image(monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import ImageDraw, ImageFont

    image = Image.new("RGB", (900, 180), "white")
    ImageDraw.Draw(image).text(
        (20, 40), "TRANSFERENCIA MARIA 12345", fill="black",
        font=ImageFont.truetype("arial.ttf", 48),
    )
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    monkeypatch.setattr(remittance_reading.PaddleOCRProvider, "is_available", lambda _: False)
    result = read_remittance(buf.getvalue())
    if "ocr_unavailable" in result["warnings"]:
        pytest.skip("Windows no tiene instalado el reconocedor es-MX")
    assert "MARIA" in result["text"]
    assert "12345" in result["text"]
    assert "ocr_language_fallback" in result["warnings"]


def test_rejects_invalid_large_and_excessive_pages() -> None:
    with pytest.raises(RemittanceReadingError):
        read_remittance(b"no es un comprobante")
    with pytest.raises(RemittanceReadingError):
        read_remittance(b"x" * (remittance_reading.MAX_BYTES + 1))
    document = pymupdf.open()
    for _ in range(11):
        document.new_page()
    data = document.tobytes()
    document.close()
    with pytest.raises(RemittanceReadingError, match="10 páginas"):
        read_remittance(data)


def test_api_returns_temporary_text_without_cache() -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Test transfer bank document example")
    data = document.tobytes()
    document.close()
    response = TestClient(app).post(
        "/api/v1/remittances/read", files={"file": ("fake.pdf", data, "application/pdf")}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "Test transfer" in response.json()["text"]
