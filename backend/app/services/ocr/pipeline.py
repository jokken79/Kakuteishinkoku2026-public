"""Pipeline OCR: imagen -> texto -> parse -> validacion -> 仕訳 candidato.

Orquesta los pasos del plan 04 §3:

    image_bytes
      -> provider.extract (con fallback chain + consentimiento)
      -> parse_receipt
      -> validacion (cuadre aritmetico; 税≈base*rate; fecha plausible;
         registro/checksum; score global)
      -> propuesta de Transaction + JournalEntry candidato (科目 del clasificador)

Reglas de seguridad (NUNCA auto-registrar):
- Si el cuadre aritmetico falla (base+税 != total) o el 登録番号 no valida
  (siendo 適格請求書 esperado), la propuesta queda ``pending`` para revision.
- La confianza ALTA solo se concede si todas las validaciones criticas pasan y
  el score del OCR supera el umbral.

El pipeline NO persiste: devuelve un `ReceiptProcessingResult` (datos puros) que
el endpoint convierte en entidades (Transaction/JournalEntry/Evidence).
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.models.enums import TransactionStatus
from app.services.ocr.base import OCRProvider, OCRProviderUnavailableError, OcrRawResult
from app.services.ocr.classifier import (
    AccountClassifier,
    AccountSuggestion,
    get_default_classifier,
)
from app.services.ocr.ensemble import ConsensusResult, vote_fields
from app.services.ocr.parsers import ParsedReceipt, parse_receipt
from app.services.ocr.preprocess import preprocess_image
from app.services.ocr.registry import resolve_chain

logger = logging.getLogger(__name__)

# Tolerancia (en yenes) para el cuadre aritmetico (redondeos del 消費税).
_ROUNDING_TOLERANCE = 2
# Umbral de score OCR para confianza ALTA.
_HIGH_CONFIDENCE_THRESHOLD = 0.75
# Umbral de confianza por debajo del cual el ensemble dispara un 2do voto.
_LOW_CONFIDENCE_THRESHOLD = 0.6


@dataclass
class ValidationResult:
    """Resultado de las validaciones del recibo parseado.

    Args:
        arithmetic_ok: ``True`` si base+税 cuadra con el total (dentro de
            tolerancia), o si no hay datos suficientes para refutar.
        tax_consistent: ``True`` si 税 ≈ base*rate en cada linea.
        date_ok: ``True`` si la fecha es plausible (presente y no futura).
        registration_ok: ``True`` si no hay 登録番号, o si lo hay y su checksum
            valida.
        score: Score global de validacion (0.0-1.0).
        errors: Lista de mensajes de los chequeos que fallaron.
    """

    arithmetic_ok: bool = True
    tax_consistent: bool = True
    date_ok: bool = True
    registration_ok: bool = True
    score: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def is_blocking(self) -> bool:
        """``True`` si algun chequeo critico impide el auto-registro."""
        return not (self.arithmetic_ok and self.registration_ok)


@dataclass
class JournalLineCandidate:
    """Linea candidata de 仕訳 (sin persistir).

    Args:
        side: ``debit`` o ``credit``.
        account_code: Codigo de cuenta.
        amount: Importe (entero yenes).
        tax_rate: Tasa de consumo de la linea (o ``None``).
    """

    side: str
    account_code: str
    amount: int
    tax_rate: int | None = None


@dataclass
class JournalEntryCandidate:
    """Asiento candidato (cabecera + lineas), sin persistir.

    Args:
        date: Fecha del asiento.
        description: 摘要.
        lines: Lineas del asiento (Σ借方 = Σ貸方).
    """

    date: datetime.date | None
    description: str
    lines: list[JournalLineCandidate] = field(default_factory=list)


@dataclass
class ReceiptProcessingResult:
    """Resultado completo del pipeline para un recibo.

    Args:
        parsed: Recibo parseado (campos + confianzas).
        validation: Resultado de las validaciones.
        account_suggestion: 勘定科目 sugerido por el clasificador.
        journal_candidate: Asiento candidato propuesto.
        status: Estado propuesto (``pending``/``confirmed`` nunca auto).
        confidence_level: ``"high"`` o ``"low"``.
        provider_used: Nombre del proveedor que produjo el texto.
        overall_confidence: Confianza combinada (OCR + validacion).
        consensus: Resultado del voto ensemble (si corrio un 2do provider), o
            ``None`` si el ensemble no se aplico.
    """

    parsed: ParsedReceipt
    validation: ValidationResult
    account_suggestion: AccountSuggestion
    journal_candidate: JournalEntryCandidate
    status: TransactionStatus
    confidence_level: str
    provider_used: str
    overall_confidence: float
    consensus: ConsensusResult | None = None


def validate_receipt(
    parsed: ParsedReceipt, *, today: datetime.date | None = None
) -> ValidationResult:
    """Valida el cuadre aritmetico, consistencia de tasa, fecha y registro.

    Args:
        parsed: Recibo parseado.
        today: Fecha de referencia para el filtro de futuro.

    Returns:
        `ValidationResult` con flags, score y errores.
    """
    ref = today or datetime.date.today()
    result = ValidationResult()

    # 1. Fecha plausible (presente y no futura).
    if parsed.date is None:
        result.date_ok = False
        result.errors.append("Fecha no detectada.")
    elif parsed.date > ref:
        result.date_ok = False
        result.errors.append(f"Fecha futura: {parsed.date.isoformat()}.")

    # 2. Consistencia de tasa por linea (税 ≈ base * rate / 100).
    for line in parsed.tax_lines:
        base = line.get("base")
        tax = line.get("tax")
        rate = line.get("rate")
        if base is None or tax is None or rate is None:
            continue
        expected = round(base * rate / 100)
        if abs(expected - tax) > _ROUNDING_TOLERANCE:
            result.tax_consistent = False
            result.errors.append(
                f"消費税 inconsistente en {rate}%: esperado~{expected}, leido {tax}."
            )

    # 3. Cuadre aritmetico: Σ(base+tax) ≈ total.
    if parsed.total is not None and parsed.tax_lines:
        sum_lines = sum(
            (line.get("base") or 0) + (line.get("tax") or 0) for line in parsed.tax_lines
        )
        if abs(sum_lines - parsed.total) > _ROUNDING_TOLERANCE:
            result.arithmetic_ok = False
            result.errors.append(
                f"Cuadre fallido: Σ(base+税)={sum_lines} != total={parsed.total}."
            )

    # 4. 登録番号: si esta presente debe validar checksum.
    if parsed.registration_number is not None and not parsed.is_qualified_invoice:
        result.registration_ok = False
        result.errors.append(
            f"登録番号 con checksum invalido: {parsed.registration_number}."
        )

    # Score: promedio de los 4 flags ponderado por la confianza del parseo.
    flags = [
        result.arithmetic_ok,
        result.tax_consistent,
        result.date_ok,
        result.registration_ok,
    ]
    flag_score = sum(1 for f in flags if f) / len(flags)
    result.score = round(flag_score * (parsed.confidence or 0.0), 4)
    return result


def _build_journal_candidate(
    parsed: ParsedReceipt, suggestion: AccountSuggestion
) -> JournalEntryCandidate:
    """Construye el asiento candidato (gasto al 借方, 事業主借 al 貸方).

    Para un gasto pagado por el titular: 借方 = cuenta de gasto (por tasa),
    貸方 = 事業主借 (312) por el total. Σ借方 = Σ貸方.

    Args:
        parsed: Recibo parseado.
        suggestion: 勘定科目 sugerido para el gasto.

    Returns:
        `JournalEntryCandidate` balanceado.
    """
    lines: list[JournalLineCandidate] = []
    total = parsed.total or 0

    if parsed.tax_lines and all(
        (tl.get("base") is not None and tl.get("tax") is not None) for tl in parsed.tax_lines
    ):
        # Una linea de gasto por tasa (税込 = base + tax), 区分経理.
        debit_sum = 0
        for tl in parsed.tax_lines:
            amount = (tl.get("base") or 0) + (tl.get("tax") or 0)
            debit_sum += amount
            lines.append(
                JournalLineCandidate(
                    side="debit",
                    account_code=suggestion.account_code,
                    amount=amount,
                    tax_rate=tl.get("rate"),
                )
            )
        credit_amount = debit_sum
    else:
        # Sin split: una sola linea de gasto por el total.
        lines.append(
            JournalLineCandidate(
                side="debit", account_code=suggestion.account_code, amount=total
            )
        )
        credit_amount = total

    lines.append(
        JournalLineCandidate(side="credit", account_code="312", amount=credit_amount)
    )

    description = parsed.vendor or "OCR 領収書"
    return JournalEntryCandidate(date=parsed.date, description=description, lines=lines)


def _extract_with_chain(
    image_bytes: bytes, chain: list[OCRProvider]
) -> tuple[OcrRawResult, OCRProvider]:
    """Intenta cada provider de la cadena hasta obtener texto.

    Args:
        image_bytes: Bytes de la imagen (ya preprocesada).
        chain: Cadena de providers en orden de preferencia.

    Returns:
        Tupla ``(raw_result, provider)`` del primer provider que produjo texto.

    Raises:
        OCRProviderUnavailableError: Si ningun provider produjo texto.
    """
    last_error: Exception | None = None
    for provider in chain:
        try:
            raw = provider.extract(image_bytes)
            if raw and raw.raw_text.strip():
                return raw, provider
        except Exception as exc:  # noqa: BLE001 — fallback robusto entre providers
            last_error = exc
            logger.warning("Provider '%s' fallo: %s", provider.name, exc)
            continue
    raise OCRProviderUnavailableError(
        f"Ningun proveedor produjo texto. Ultimo error: {last_error}"
    )


def _postcorrect(
    image_bytes: bytes,
    provider: OCRProvider,
    parsed: ParsedReceipt,
    validation: ValidationResult,
    *,
    today: datetime.date | None,
) -> tuple[OcrRawResult, ParsedReceipt, ValidationResult] | None:
    """Re-pregunta una vez al provider LLM si el cuadre aritmetico fallo.

    Research §5.5: si los numeros no suman, mostrarle el error al LLM y pedir una
    correccion suele rescatar el recibo. Un SOLO reintento (no loop). Solo aplica
    a providers que exponen ``extract_with_hint`` (los LLM); si no, devuelve
    ``None`` (no hay post-correccion posible).

    Args:
        image_bytes: Bytes de la imagen (ya preprocesada).
        provider: Provider que produjo el resultado original.
        parsed: Parseo original.
        validation: Validacion original (que fallo el cuadre).
        today: Fecha de referencia.

    Returns:
        La nueva tripleta ``(raw, parsed, validation)`` si la correccion mejoro el
        cuadre; ``None`` si no aplica o no mejoro.
    """
    hint_fn = getattr(provider, "extract_with_hint", None)
    if not callable(hint_fn):
        return None
    error_msg = "; ".join(validation.errors) or "Los importes no cuadran."
    hint = (
        f"En tu respuesta anterior estos numeros no cuadran: {error_msg}. "
        "Revisá la imagen y corregí SOLO los digitos mal leidos; si seguís sin "
        "poder leerlos con certeza, devolvé null (no inventes)."
    )
    try:
        raw2 = hint_fn(image_bytes, hint)
    except Exception as exc:  # noqa: BLE001 — la post-correccion nunca rompe el flujo.
        logger.warning("Post-correccion fallo en '%s': %s", provider.name, exc)
        return None
    if not raw2 or not raw2.raw_text.strip():
        return None
    parsed2 = parse_receipt(raw2)
    validation2 = validate_receipt(parsed2, today=today)
    if validation2.arithmetic_ok and not validation.arithmetic_ok:
        logger.info("Post-correccion rescato el cuadre en '%s'.", provider.name)
        return raw2, parsed2, validation2
    return None


def _run_ensemble(
    image_bytes: bytes,
    chain: list[OCRProvider],
    used: OCRProvider,
    parsed: ParsedReceipt,
    *,
    today: datetime.date | None,
) -> ConsensusResult | None:
    """Corre un 2do provider de la cadena y vota campo a campo (research §5.4).

    Elige el primer provider de la cadena distinto al ya usado, extrae y compara.
    El consentimiento ya esta respetado: ``chain`` solo trae providers usables.

    Args:
        image_bytes: Bytes de la imagen (ya preprocesada).
        chain: Cadena de providers usables.
        used: Provider que ya produjo el resultado primario.
        parsed: Parseo primario.
        today: Fecha de referencia (no usada aqui, reservada para coherencia).

    Returns:
        `ConsensusResult` del voto, o ``None`` si no hay 2do provider o fallo.
    """
    second = next((p for p in chain if p.name != used.name), None)
    if second is None:
        return None
    try:
        raw2 = second.extract(image_bytes)
    except Exception as exc:  # noqa: BLE001 — el 2do voto es best-effort.
        logger.warning("Ensemble: 2do provider '%s' fallo: %s", second.name, exc)
        return None
    if not raw2 or not raw2.raw_text.strip():
        return None
    parsed2 = parse_receipt(raw2)
    return vote_fields(parsed, parsed2)


def process_receipt(
    image_bytes: bytes,
    *,
    providers: list[OCRProvider] | None = None,
    classifier: AccountClassifier | None = None,
    today: datetime.date | None = None,
    settings: Settings | None = None,
) -> ReceiptProcessingResult:
    """Procesa un recibo de punta a punta (sin persistir).

    Etapas (research §5):

    1. **Preproceso** de imagen (deskew/CLAHE/denoise/binarizacion/upscale) si
       ``ocr_preprocess_enabled`` (degrada con gracia si falta OpenCV).
    2. Resolucion de cadena de providers (on/off + consentimiento) y extraccion
       con fallback.
    3. parse + validacion (cuadre aritmetico, checksum 登録番号, ...).
    4. **Post-correccion** LLM opt-in: si el cuadre falla y el provider lo soporta,
       un reintento mostrandole el error.
    5. **Ensemble** opt-in: si la validacion bloquea o la confianza es baja, un 2do
       provider vota campo a campo (los campos en disputa fuerzan ``pending``).

    Args:
        image_bytes: Bytes de la imagen/PDF del recibo.
        providers: Cadena de proveedores a usar. Si es ``None`` se resuelve de
            `Settings` (registry). Util para inyectar `FakeOCRProvider` en tests.
        classifier: Clasificador de 科目. Si es ``None`` usa el de reglas.
        today: Fecha de referencia para validaciones de futuro.
        settings: Settings a usar (preproceso/ensemble/post-correccion). Si es
            ``None`` usa `get_settings()`.

    Returns:
        `ReceiptProcessingResult` con el parseo, validacion y 仕訳 candidato.

    Raises:
        OCRProviderUnavailableError: Si ningun proveedor de la cadena pudo
            producir texto.
    """
    cfg = settings or get_settings()
    chain = providers if providers is not None else resolve_chain(cfg)
    if not chain:
        raise OCRProviderUnavailableError(
            "No hay proveedores OCR usables (revisar enabled/credenciales/consentimiento)."
        )

    # 1. Preproceso (mayor salto de precision; beneficia a TODOS los providers).
    image_for_ocr = image_bytes
    if cfg.ocr_preprocess_enabled:
        image_for_ocr = preprocess_image(image_bytes)

    # 2. Extraccion con fallback chain.
    raw, used = _extract_with_chain(image_for_ocr, chain)

    parsed = parse_receipt(raw)
    validation = validate_receipt(parsed, today=today)

    # 4. Post-correccion LLM (opt-in) si el cuadre fallo.
    if cfg.ocr_postcorrection_enabled and not validation.arithmetic_ok:
        corrected = _postcorrect(
            image_for_ocr, used, parsed, validation, today=today
        )
        if corrected is not None:
            raw, parsed, validation = corrected

    # 5. Ensemble (opt-in) si bloquea o la confianza es baja.
    consensus: ConsensusResult | None = None
    if cfg.ocr_ensemble_enabled and (
        validation.is_blocking or parsed.confidence < _LOW_CONFIDENCE_THRESHOLD
    ):
        consensus = _run_ensemble(
            image_for_ocr, chain, used, parsed, today=today
        )

    clf = classifier or get_default_classifier()
    suggestion = clf.suggest(parsed.vendor, parsed.raw_text)
    journal = _build_journal_candidate(parsed, suggestion)

    # Confianza combinada y nivel.
    overall = round((parsed.confidence + validation.score) / 2, 4)
    # Campos en disputa del ensemble bajan la confianza y fuerzan revision.
    disputes = bool(consensus and consensus.has_disputes)
    high = (
        not validation.is_blocking
        and validation.date_ok
        and validation.tax_consistent
        and not disputes
        and overall >= _HIGH_CONFIDENCE_THRESHOLD
    )
    confidence_level = "high" if high else "low"

    # NUNCA auto-registrar: todo recibo nace pending; el frontend confirma.
    # Si el cuadre/registro fallan, queda pending si o si (is_blocking).
    status = TransactionStatus.PENDING

    return ReceiptProcessingResult(
        parsed=parsed,
        validation=validation,
        account_suggestion=suggestion,
        journal_candidate=journal,
        status=status,
        confidence_level=confidence_level,
        provider_used=raw.provider,
        overall_confidence=overall,
        consensus=consensus,
    )
