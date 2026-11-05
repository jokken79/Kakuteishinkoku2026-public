"""Proveedores OCR concretos (todos con imports lazy de su dependencia)."""

from app.services.ocr.providers.azure import AzureDocIntelligenceProvider
from app.services.ocr.providers.fake import FakeOCRProvider
from app.services.ocr.providers.gemini import GeminiVisionProvider
from app.services.ocr.providers.glm import GLMOCRProvider
from app.services.ocr.providers.google import GoogleDocAIProvider
from app.services.ocr.providers.ollama import OllamaOCRProvider
from app.services.ocr.providers.paddle import PaddleOCRProvider

__all__ = [
    "AzureDocIntelligenceProvider",
    "FakeOCRProvider",
    "GLMOCRProvider",
    "GeminiVisionProvider",
    "GoogleDocAIProvider",
    "OllamaOCRProvider",
    "PaddleOCRProvider",
]
