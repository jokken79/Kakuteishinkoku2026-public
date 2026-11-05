"""Servicio OCR de recibos japoneses (Fase 2).

Arquitectura multi-proveedor con on/off + consentimiento:

- `base`       — contrato comun (`OcrRawResult`, `OCRProvider`).
- `providers`  — implementaciones (paddle/azure/google/gemini/fake), imports lazy.
- `parsers`    — logica pura: date/amount/tax_rate/reg_number/vendor + `parse_receipt`.
- `classifier` — sugerencia de 勘定科目 (reusa el vendor_mapping del seed).
- `registry`   — factory que resuelve providers segun enabled + consentimiento.
- `pipeline`   — orquesta extract -> parse -> validacion -> 仕訳 candidato.
"""

from app.services.ocr.base import (
    OcrBlock,
    OCRProvider,
    OCRProviderUnavailableError,
    OcrRawResult,
)
from app.services.ocr.classifier import AccountSuggestion, get_default_classifier
from app.services.ocr.ensemble import ConsensusResult, vote_fields
from app.services.ocr.parsers import ParsedReceipt, parse_receipt
from app.services.ocr.pipeline import (
    ReceiptProcessingResult,
    process_receipt,
    validate_receipt,
)
from app.services.ocr.preprocess import (
    PreprocessConfig,
    opencv_available,
    preprocess_image,
)
from app.services.ocr.quota import (
    CLOUD_PROVIDERS,
    daily_limit,
    is_over_limit,
    record_usage,
    usage_report,
    usage_today,
)
from app.services.ocr.registry import (
    ProviderStatus,
    provider_statuses,
    resolve_chain,
)
from app.services.ocr.structured import (
    ReceiptStructured,
    derive_confidence,
    parse_structured_response,
)

__all__ = [
    "CLOUD_PROVIDERS",
    "AccountSuggestion",
    "ConsensusResult",
    "OCRProvider",
    "OCRProviderUnavailableError",
    "OcrBlock",
    "OcrRawResult",
    "ParsedReceipt",
    "PreprocessConfig",
    "ProviderStatus",
    "ReceiptProcessingResult",
    "ReceiptStructured",
    "daily_limit",
    "derive_confidence",
    "get_default_classifier",
    "is_over_limit",
    "opencv_available",
    "parse_receipt",
    "parse_structured_response",
    "preprocess_image",
    "process_receipt",
    "provider_statuses",
    "record_usage",
    "resolve_chain",
    "usage_report",
    "usage_today",
    "validate_receipt",
    "vote_fields",
]
