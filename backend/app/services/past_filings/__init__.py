"""Servicio de 過去の申告 (archivo histórico de declaraciones anteriores).

Expone la extracción de montos clave de un PDF de 確定申告 viejo
(`extract_past_filing`) y el dataclass de resultado (`ExtractedFiling`).
"""

from app.services.past_filings.extractor import (
    ExtractedFiling,
    extract_past_filing,
    extract_text_from_pdf,
)

__all__ = [
    "ExtractedFiling",
    "extract_past_filing",
    "extract_text_from_pdf",
]
