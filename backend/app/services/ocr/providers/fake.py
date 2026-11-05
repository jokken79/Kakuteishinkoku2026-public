"""Proveedor OCR sintetico para tests (sin dependencias externas).

Devuelve un `OcrRawResult` determinista que simula un recibo japones tipico
con doble tasa (8% 軽減 y 10%), 登録番号 valido, fecha en era 令和 y total 税込.
No procesa la imagen: ignora ``image_bytes`` y siempre esta disponible.
"""

from __future__ import annotations

from app.services.ocr.base import OcrBlock, OCRProvider, OcrRawResult

# 登録番号 con checksum valido segun el algoritmo de `reg_number.validate_checksum`.
# base 12 digitos = "234567890123" -> digito de control 9 -> T9234567890123.
_VALID_REG = "T9234567890123"

# Recibo sintetico: スーパー con bloques 内8%対象 / 内10%対象 y 消費税 por tasa.
_SYNTHETIC_RECEIPT = (
    "スーパーマルショク 新宿店\n"
    "東京都新宿区西新宿1-2-3\n"
    f"登録番号 {_VALID_REG}\n"
    "令和6年5月3日\n"
    "牛乳 ※        198円\n"
    "食パン ※      150円\n"
    "ノート       300円\n"
    "ボールペン   220円\n"
    "内8%対象     348円\n"
    "内消費税(8%)   25円\n"
    "内10%対象    520円\n"
    "内消費税(10%)  47円\n"
    "合計（税込）  868円\n"
)


class FakeOCRProvider(OCRProvider):
    """Proveedor OCR falso y determinista para tests.

    Args:
        text: Texto a devolver. Si es ``None`` usa el recibo sintetico estandar.
        confidence: Confianza global a reportar.
    """

    name = "fake"
    sends_data_externally = False

    def __init__(self, text: str | None = None, confidence: float = 0.95) -> None:
        self._text = text if text is not None else _SYNTHETIC_RECEIPT
        self._confidence = confidence

    def is_available(self) -> bool:
        """El proveedor fake siempre esta disponible.

        Returns:
            Siempre ``True``.
        """
        return True

    def extract(self, image_bytes: bytes) -> OcrRawResult:
        """Devuelve el recibo sintetico, ignorando la imagen.

        Args:
            image_bytes: Ignorado.

        Returns:
            `OcrRawResult` determinista del recibo sintetico.
        """
        blocks = [
            OcrBlock(text=line, bbox=[0, i * 20, 200, i * 20 + 18], confidence=self._confidence)
            for i, line in enumerate(self._text.splitlines())
            if line.strip()
        ]
        return OcrRawResult(
            raw_text=self._text,
            blocks=blocks,
            provider=self.name,
            overall_confidence=self._confidence,
        )
