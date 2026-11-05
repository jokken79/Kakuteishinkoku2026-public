"""Importacion de XML de 控除証明書 electrónicos (e-Tax / NTA).

Expone el parser de los XML oficiales de 控除証明書 (生命保険・地震保険・iDeCo・
国民年金・寄附金) que detecta el tipo, extrae el 控除額 y arma una Deduction
candidata para el flujo preview -> commit (espejo del import de CSV).
"""

from app.services.import_xml.koujo_parser import (
    KoujoParseError,
    KoujoParseResult,
    parse_koujo_xml,
)

__all__ = ["KoujoParseError", "KoujoParseResult", "parse_koujo_xml"]
