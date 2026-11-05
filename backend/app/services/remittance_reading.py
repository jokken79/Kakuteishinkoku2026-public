"""Lectura temporal de comprobantes bancarios, sin clasificar ni persistir."""

from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
from pathlib import Path

import pymupdf
from PIL import Image, UnidentifiedImageError

from app.services.ocr.providers.paddle import PaddleOCRProvider

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 10
MAX_PIXELS = 20_000_000
MAX_TEXT = 30_000


class RemittanceReadingError(ValueError):
    """Archivo no admitido o demasiado grande para la lectura temporal."""


def _windows_ocr(image: bytes, language: str) -> str | None:
    """Usa el reconocedor instalado de Windows, sin crear un archivo de imagen."""
    if sys.platform != "win32":
        return None
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    script = Path(__file__).parent / "ocr" / "windows_remittance_ocr.ps1"
    try:
        result = subprocess.run(  # noqa: S603
            [str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script), "-Language", language],
            input=base64.b64encode(image), capture_output=True, timeout=45, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _local_ocr(image: bytes, warnings: list[str], language: str) -> str:
    provider = PaddleOCRProvider(lang=language)
    paddle_failed = False
    if provider.is_available():
        try:
            return provider.extract(image).raw_text
        except Exception:
            # Nunca registrar excepciones que puedan contener datos del documento.
            paddle_failed = True
    text = _windows_ocr(image, language)
    if text is not None:
        if language == "pt" and "ocr_language_fallback" not in warnings:
            warnings.append("ocr_language_fallback")
        return text
    if "ocr_unavailable" not in warnings:
        warnings.append("ocr_unavailable")
    if paddle_failed and "ocr_failed" not in warnings:
        warnings.append("ocr_failed")
    return ""


def read_remittance(data: bytes, language: str = "pt") -> dict[str, object]:
    """Extrae texto localmente; no verifica autenticidad ni guarda el archivo."""
    if not data or len(data) > MAX_BYTES:
        raise RemittanceReadingError("Archivo vacío o superior a 10 MB.")
    warnings: list[str] = []
    pages: list[str] = []
    if data.startswith(b"%PDF-"):
        try:
            with pymupdf.open(stream=data, filetype="pdf") as document:  # type: ignore[no-untyped-call]
                if document.needs_pass:
                    raise RemittanceReadingError("El PDF está protegido con contraseña.")
                if len(document) > MAX_PAGES:
                    raise RemittanceReadingError("El PDF supera el máximo de 10 páginas.")
                for page in document:
                    text = page.get_text("text").strip()
                    # Un encabezado seleccionable puede coexistir con un escaneo
                    # grande. No dejar que ese texto oculte la imagen del recibo.
                    page_area = page.rect.width * page.rect.height
                    has_large_image = any(
                        (
                            pymupdf.Rect(info["bbox"])  # type: ignore[no-untyped-call]
                            & page.rect
                        ).get_area() >= page_area * 0.2
                        for info in page.get_image_info()
                    ) if page_area > 0 else False
                    if len(text) < 20 or has_large_image:
                        rect = page.rect
                        too_large = rect.width * rect.height * 4 > MAX_PIXELS
                        if rect.width <= 0 or rect.height <= 0 or too_large:
                            warnings.append("page_too_large")
                        else:
                            matrix = pymupdf.Matrix(2, 2)  # type: ignore[no-untyped-call]
                            image = page.get_pixmap(matrix=matrix, alpha=False).tobytes("png")
                            ocr_text = _local_ocr(image, warnings, language).strip()
                            if ocr_text and text and has_large_image:
                                text = (
                                    f"{text}\n\n[OCR de la página; puede repetir texto]\n{ocr_text}"
                                )
                            else:
                                text = ocr_text or text
                    pages.append(text)
        except RemittanceReadingError:
            raise
        except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
            raise RemittanceReadingError("No se pudo abrir el PDF.") from exc
    else:
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG"}:
                    raise RemittanceReadingError("Solo se admiten PDF, PNG y JPEG.")
                if image.width * image.height > MAX_PIXELS:
                    raise RemittanceReadingError("La imagen supera el máximo de 20 megapíxeles.")
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise RemittanceReadingError("La imagen no es válida.") from exc
        pages.append(_local_ocr(data, warnings, language).strip())

    text = "\n\n".join(
        f"--- Página {index} ---\n{page}" for index, page in enumerate(pages, 1) if page
    )
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT]
        warnings.append("text_truncated")
    if not text:
        warnings.append("no_text")
    empty_pages = [index for index, page in enumerate(pages, 1) if not page]
    return {"text": text, "warnings": warnings, "pages": len(pages), "empty_pages": empty_pages}
