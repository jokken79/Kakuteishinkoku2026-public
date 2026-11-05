"""Reglas de ciclo de vida y persistencia de 売上書類."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import FiscalYear, Taxpayer
from app.models.enums import (
    SalesDocumentStatus,
    SalesDocumentType,
    SalesPaymentMethod,
    SalesPriceMode,
    SalesTaxCategory,
    TaxRoundingMode,
)
from app.models.sales_documents import (
    BusinessProfile,
    Customer,
    SalesDocument,
    SalesDocumentArtifact,
    SalesDocumentEvent,
    SalesDocumentLine,
    SalesDocumentSequence,
    SalesPayment,
)
from app.services.sales_documents.calculations import (
    CalculatedLine,
    calculate_totals,
    line_amount,
)
from app.services.sales_documents.pdf import render_sales_document

_REGISTRATION_NUMBER = re.compile(r"^T\d{13}$")
_PREFIX = {
    SalesDocumentType.ESTIMATE: "EST",
    SalesDocumentType.DELIVERY_NOTE: "DEL",
    SalesDocumentType.INVOICE: "INV",
    SalesDocumentType.RECEIPT: "REC",
    SalesDocumentType.PURCHASE_ORDER: "PO",
    SalesDocumentType.ORDER_ACKNOWLEDGEMENT: "ACK",
    SalesDocumentType.CONSOLIDATED_INVOICE: "CIN",
    SalesDocumentType.CORRECTED_INVOICE: "CRN",
}
_PAYABLE_TYPES = {
    SalesDocumentType.INVOICE,
    SalesDocumentType.CONSOLIDATED_INVOICE,
    SalesDocumentType.CORRECTED_INVOICE,
}
_DEFAULT_LOGO_REF = None
_QUALIFIED_INVOICE_TYPES = _PAYABLE_TYPES | {SalesDocumentType.RECEIPT}
_PAYMENT_METHOD_LABEL = {
    SalesPaymentMethod.CASH: "現金",
    SalesPaymentMethod.BANK_TRANSFER: "銀行振込",
    SalesPaymentMethod.CARD: "カード",
    SalesPaymentMethod.OTHER: "その他",
}


class SalesDocumentError(ValueError):
    """Error de negocio con código estable para la API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def get_taxpayer(session: Session) -> Taxpayer:
    taxpayer = session.scalar(select(Taxpayer).order_by(Taxpayer.created_at).limit(1))
    if taxpayer is None:
        raise SalesDocumentError("taxpayer_not_found", "事業者情報を先に登録してください。")
    return taxpayer


def get_or_create_profile(session: Session, taxpayer: Taxpayer) -> BusinessProfile:
    profile = session.scalar(
        select(BusinessProfile).where(BusinessProfile.taxpayer_id == taxpayer.id)
    )
    if profile is None:
        profile = BusinessProfile(
            taxpayer_id=taxpayer.id,
            trade_name="事業者",
            legal_name=taxpayer.name,
            representative_name=taxpayer.name,
            contact_person_name=taxpayer.name,
            postal_code=taxpayer.postal_code,
            address=taxpayer.address,
            address_line1=taxpayer.address,
            logo_ref=_DEFAULT_LOGO_REF,
            show_logo=False,
        )
        session.add(profile)
        session.flush()
    return profile


def profile_snapshot(profile: BusinessProfile) -> dict[str, object]:
    return {
        "trade_name": profile.trade_name,
        "legal_name": profile.legal_name,
        "legal_name_kana": profile.legal_name_kana,
        "corporate_number": profile.corporate_number,
        "business_description": profile.business_description,
        "show_representative": profile.show_representative,
        "representative_name": profile.representative_name,
        "department_name": profile.department_name,
        "contact_person_name": profile.contact_person_name,
        "postal_code": profile.postal_code,
        "address": profile.address,
        "address_line1": profile.address_line1,
        "address_line2": profile.address_line2,
        "phone": profile.phone,
        "fax": profile.fax,
        "email": profile.email,
        "website_url": profile.website_url,
        "default_customer_honorific": profile.default_customer_honorific,
        "payment_terms_days": profile.payment_terms_days,
        "bank_name": profile.bank_name,
        "bank_branch": profile.bank_branch,
        "bank_account_type": profile.bank_account_type,
        "bank_account_number": profile.bank_account_number,
        "bank_account_holder": profile.bank_account_holder,
        "show_bank_details": profile.show_bank_details,
        "logo_ref": profile.logo_ref,
        "seal_ref": profile.seal_ref,
        "show_stamp_box": profile.show_stamp_box,
        "show_logo": profile.show_logo,
        "show_seal": profile.show_seal,
        "seal_text": profile.seal_text,
        "registration_number": (
            profile.registration_number
            if profile.is_invoice_issuer and profile.show_registration_number
            else None
        ),
        "show_registration_number": profile.show_registration_number,
        "invoice_message": profile.invoice_message,
        "receipt_message": profile.receipt_message,
        "receipt_proviso": profile.receipt_proviso,
        "transfer_fee_note": profile.transfer_fee_note,
        "document_footer_note": profile.document_footer_note,
    }


def customer_snapshot(customer: Customer) -> dict[str, object]:
    return {
        "name": customer.name,
        "honorific": customer.honorific,
        "postal_code": customer.postal_code,
        "address": customer.address,
        "contact_name": customer.contact_name,
        "email": customer.email,
        "phone": customer.phone,
    }


def resolve_fiscal_year(session: Session, taxpayer_id: object, year: int) -> FiscalYear | None:
    return session.scalar(
        select(FiscalYear).where(
            FiscalYear.taxpayer_id == taxpayer_id,
            FiscalYear.year == year,
        )
    )


def replace_lines(
    document: SalesDocument,
    lines: list[tuple[str, Decimal, str, int, int, SalesTaxCategory]],
) -> None:
    if document.status != SalesDocumentStatus.DRAFT:
        raise SalesDocumentError("document_locked", "発行済みの書類は編集できません。")
    document.lines.clear()
    calculated: list[CalculatedLine] = []
    for position, (description, quantity, unit, unit_price, discount, category) in enumerate(lines):
        amount = line_amount(quantity, unit_price, discount)
        document.lines.append(
            SalesDocumentLine(
                position=position,
                description=description,
                quantity=quantity,
                unit=unit,
                unit_price=unit_price,
                discount_amount=discount,
                tax_category=category,
                amount=amount,
            )
        )
        calculated.append(CalculatedLine(amount=amount, tax_category=category))
    totals = calculate_totals(
        calculated,
        rounding_mode=document.rounding_mode,
        price_mode=document.price_mode,
    )
    document.subtotal = totals.subtotal
    document.tax_8 = totals.tax_8
    document.tax_10 = totals.tax_10
    document.total = totals.total


def _next_number(session: Session, document: SalesDocument) -> str:
    year = document.issue_date.year
    sequence = session.scalar(
        select(SalesDocumentSequence)
        .where(
            SalesDocumentSequence.taxpayer_id == document.taxpayer_id,
            SalesDocumentSequence.document_type == document.document_type,
            SalesDocumentSequence.year == year,
        )
        .with_for_update()
    )
    if sequence is None:
        sequence = SalesDocumentSequence(
            taxpayer_id=document.taxpayer_id,
            document_type=document.document_type,
            year=year,
            next_value=2,
        )
        session.add(sequence)
        value = 1
    else:
        value = sequence.next_value
        sequence.next_value += 1
    session.flush()
    return f"{_PREFIX[document.document_type]}-{year}-{value:04d}"


def _validate_for_issue(document: SalesDocument, profile: BusinessProfile) -> None:
    if not document.lines:
        raise SalesDocumentError("lines_required", "明細を1件以上入力してください。")
    if document.total <= 0:
        raise SalesDocumentError("positive_total_required", "合計金額は1円以上必要です。")
    if not str(document.customer_snapshot.get("name", "")).strip():
        raise SalesDocumentError("customer_required", "取引先名を入力してください。")
    if document.is_qualified_invoice:
        if document.document_type not in _QUALIFIED_INVOICE_TYPES:
            raise SalesDocumentError(
                "invalid_qualified_type",
                "適格請求書は請求書または領収書として作成してください。",
            )
        if not profile.is_invoice_issuer or not profile.registration_number:
            raise SalesDocumentError(
                "invoice_profile_required", "設定で適格請求書発行事業者を有効にしてください。"
            )
        if not _REGISTRATION_NUMBER.fullmatch(profile.registration_number):
            raise SalesDocumentError(
                "invalid_registration_number", "登録番号はTと13桁の数字で入力してください。"
            )


def add_event(
    session: Session,
    document: SalesDocument,
    event_type: str,
    payload: dict[str, object] | None = None,
) -> None:
    session.add(SalesDocumentEvent(document_id=document.id, event_type=event_type, payload=payload))


def issue_document(session: Session, document: SalesDocument) -> SalesDocument:
    """Emite y archiva una copia exacta del PDF. Repetir la llamada es seguro."""
    if document.status != SalesDocumentStatus.DRAFT:
        return document
    taxpayer = session.get(Taxpayer, document.taxpayer_id)
    if taxpayer is None:
        raise SalesDocumentError("taxpayer_not_found", "事業者情報が見つかりません。")
    profile = get_or_create_profile(session, taxpayer)
    _validate_for_issue(document, profile)
    document.document_number = document.document_number or _next_number(session, document)
    document.issuer_snapshot = profile_snapshot(profile)
    document.issued_at = datetime.now(UTC)
    if document.document_type == SalesDocumentType.RECEIPT:
        document.status = SalesDocumentStatus.PAID
        document.amount_paid = document.total
    elif document.document_type in _PAYABLE_TYPES:
        document.status = SalesDocumentStatus.AWAITING_PAYMENT
    else:
        document.status = SalesDocumentStatus.ISSUED
    pdf = render_sales_document(document)
    filename = f"{document.document_number}.pdf"
    document.artifacts.append(
        SalesDocumentArtifact(
            revision=document.revision,
            filename=filename,
            content_hash=hashlib.sha256(pdf).hexdigest(),
            content=pdf,
        )
    )
    add_event(session, document, "issued", {"number": document.document_number})
    session.flush()
    return document


def convert_document(
    session: Session,
    source: SalesDocument,
    target_type: SalesDocumentType,
    *,
    creation_key: str | None = None,
) -> SalesDocument:
    """Crea un borrador relacionado, editable e idempotente."""
    if creation_key:
        existing = session.scalar(
            select(SalesDocument).where(
                SalesDocument.taxpayer_id == source.taxpayer_id,
                SalesDocument.creation_key == creation_key,
            )
        )
        if existing:
            return existing
    converted = SalesDocument(
        taxpayer_id=source.taxpayer_id,
        fiscal_year_id=source.fiscal_year_id,
        customer_id=source.customer_id,
        source_document_id=source.id,
        document_type=target_type,
        status=SalesDocumentStatus.DRAFT,
        creation_key=creation_key,
        subject=source.subject,
        issue_date=date.today(),
        due_date=source.due_date if target_type in _PAYABLE_TYPES else None,
        notes=source.notes,
        customer_snapshot=dict(source.customer_snapshot),
        rounding_mode=source.rounding_mode,
        price_mode=source.price_mode,
        is_qualified_invoice=False,
    )
    session.add(converted)
    session.flush()
    replace_lines(
        converted,
        [
            (
                line.description,
                line.quantity,
                line.unit,
                line.unit_price,
                line.discount_amount,
                line.tax_category,
            )
            for line in source.lines
        ],
    )
    add_event(session, source, "converted", {"target_id": str(converted.id), "type": target_type})
    add_event(session, converted, "created_from", {"source_id": str(source.id)})
    return converted


def mark_sent(session: Session, document: SalesDocument) -> SalesDocument:
    if document.status == SalesDocumentStatus.DRAFT:
        raise SalesDocumentError("issue_required", "送付前に書類を発行してください。")
    if document.status == SalesDocumentStatus.VOIDED:
        raise SalesDocumentError("document_voided", "取消済みの書類は送付できません。")
    if document.sent_at is None:
        document.sent_at = datetime.now(UTC)
        if document.document_type not in _PAYABLE_TYPES:
            document.status = SalesDocumentStatus.SENT
        add_event(session, document, "sent")
    return document


def void_document(session: Session, document: SalesDocument, reason: str | None) -> SalesDocument:
    if document.status == SalesDocumentStatus.VOIDED:
        return document
    if document.status == SalesDocumentStatus.PAID or document.amount_paid:
        raise SalesDocumentError("paid_document", "入金済みの書類は取消できません。")
    document.status = SalesDocumentStatus.VOIDED
    document.voided_at = datetime.now(UTC)
    add_event(session, document, "voided", {"reason": reason} if reason else None)
    return document


def register_payment(
    session: Session,
    document: SalesDocument,
    *,
    payment_date: date,
    amount: int,
    method: SalesPaymentMethod,
    reference: str | None,
    idempotency_key: str | None,
    create_receipt: bool,
) -> SalesPayment:
    if document.document_type not in _PAYABLE_TYPES:
        raise SalesDocumentError("not_payable", "この書類には入金を登録できません。")
    if document.status in {SalesDocumentStatus.DRAFT, SalesDocumentStatus.VOIDED}:
        raise SalesDocumentError("document_not_payable", "発行済みの請求書を選択してください。")
    if idempotency_key:
        existing = session.scalar(
            select(SalesPayment).where(
                SalesPayment.document_id == document.id,
                SalesPayment.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return existing
    outstanding = document.total - document.amount_paid
    if amount <= 0 or amount > outstanding:
        raise SalesDocumentError(
            "invalid_payment_amount", f"入金額は1円から{outstanding:,}円の範囲で入力してください。"
        )
    payment = SalesPayment(
        document_id=document.id,
        payment_date=payment_date,
        amount=amount,
        method=method,
        reference=reference,
        idempotency_key=idempotency_key,
    )
    session.add(payment)
    document.amount_paid += amount
    document.status = (
        SalesDocumentStatus.PAID
        if document.amount_paid == document.total
        else SalesDocumentStatus.PARTIALLY_PAID
    )
    session.flush()
    add_event(
        session,
        document,
        "payment_registered",
        {"payment_id": str(payment.id), "amount": amount},
    )
    if create_receipt:
        taxpayer = session.get(Taxpayer, document.taxpayer_id)
        if taxpayer is None:
            raise SalesDocumentError("taxpayer_not_found", "事業者情報が見つかりません。")
        profile = get_or_create_profile(session, taxpayer)
        method_label = _PAYMENT_METHOD_LABEL[method]
        reference_suffix = f" / {reference}" if reference else ""
        source_number = document.document_number or "請求書"
        receipt_subject = profile.receipt_proviso or f"{source_number} ご入金分"
        receipt = SalesDocument(
            taxpayer_id=document.taxpayer_id,
            fiscal_year_id=document.fiscal_year_id,
            customer_id=document.customer_id,
            source_document_id=document.id,
            document_type=SalesDocumentType.RECEIPT,
            status=SalesDocumentStatus.DRAFT,
            issue_date=payment_date,
            subject=receipt_subject,
            notes=profile.receipt_message or "上記金額を正に領収いたしました。",
            customer_snapshot=dict(document.customer_snapshot),
            rounding_mode=TaxRoundingMode.FLOOR,
            price_mode=SalesPriceMode.INCLUSIVE,
        )
        session.add(receipt)
        session.flush()
        replace_lines(
            receipt,
            [
                (
                    f"{source_number} ご入金分（{method_label}{reference_suffix}）",
                    Decimal("1"),
                    "式",
                    amount,
                    0,
                    SalesTaxCategory.OUT_OF_SCOPE,
                )
            ],
        )
        issue_document(session, receipt)
        payment.receipt_document_id = receipt.id
    return payment
