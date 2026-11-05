"""API de 設定 → 事業者情報 para documentos comerciales."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import SalesPriceMode, TaxRoundingMode
from app.models.sales_documents import BusinessProfile
from app.services.sales_documents.service import (
    SalesDocumentError,
    get_or_create_profile,
    get_taxpayer,
)

router = APIRouter(tags=["business-profile"])
_REGISTRATION_NUMBER = re.compile(r"^T\d{13}$")
_CORPORATE_NUMBER = re.compile(r"^\d{13}$")


class BusinessProfileOut(BaseModel):
    id: uuid.UUID
    trade_name: str
    legal_name: str | None
    legal_name_kana: str | None
    corporate_number: str | None
    business_description: str | None
    show_representative: bool
    representative_name: str | None
    department_name: str | None
    contact_person_name: str | None
    postal_code: str | None
    address: str | None
    address_line1: str | None
    address_line2: str | None
    phone: str | None
    fax: str | None
    email: str | None
    website_url: str | None
    default_customer_honorific: str
    payment_terms_days: int
    bank_name: str | None
    bank_branch: str | None
    bank_account_type: str | None
    bank_account_number: str | None
    bank_account_holder: str | None
    show_bank_details: bool
    logo_ref: str | None
    seal_ref: str | None
    show_stamp_box: bool
    show_logo: bool
    show_seal: bool
    seal_text: str | None
    is_invoice_issuer: bool
    registration_number: str | None
    show_registration_number: bool
    invoice_message: str | None
    receipt_message: str | None
    receipt_proviso: str | None
    transfer_fee_note: str | None
    document_footer_note: str | None
    rounding_mode: TaxRoundingMode
    price_mode: SalesPriceMode
    updated_at: datetime


class BusinessProfilePatch(BaseModel):
    trade_name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    legal_name_kana: str | None = Field(default=None, max_length=255)
    corporate_number: str | None = Field(default=None, max_length=13)
    business_description: str | None = Field(default=None, max_length=255)
    show_representative: bool | None = None
    representative_name: str | None = Field(default=None, max_length=255)
    department_name: str | None = Field(default=None, max_length=255)
    contact_person_name: str | None = Field(default=None, max_length=255)
    postal_code: str | None = Field(default=None, max_length=16)
    address: str | None = Field(default=None, max_length=512)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    fax: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    website_url: str | None = Field(default=None, max_length=255)
    default_customer_honorific: str | None = Field(default=None, max_length=16)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    bank_name: str | None = Field(default=None, max_length=128)
    bank_branch: str | None = Field(default=None, max_length=128)
    bank_account_type: str | None = Field(default=None, max_length=32)
    bank_account_number: str | None = Field(default=None, max_length=32)
    bank_account_holder: str | None = Field(default=None, max_length=128)
    show_bank_details: bool | None = None
    logo_ref: str | None = Field(default=None, max_length=512)
    seal_ref: str | None = Field(default=None, max_length=512)
    show_stamp_box: bool | None = None
    show_logo: bool | None = None
    show_seal: bool | None = None
    seal_text: str | None = Field(default=None, max_length=16)
    is_invoice_issuer: bool | None = None
    registration_number: str | None = Field(default=None, max_length=14)
    show_registration_number: bool | None = None
    invoice_message: str | None = None
    receipt_message: str | None = None
    receipt_proviso: str | None = Field(default=None, max_length=255)
    transfer_fee_note: str | None = Field(default=None, max_length=255)
    document_footer_note: str | None = None
    rounding_mode: TaxRoundingMode | None = None
    price_mode: SalesPriceMode | None = None


def _out(profile: BusinessProfile) -> BusinessProfileOut:
    return BusinessProfileOut(
        id=profile.id,
        trade_name=profile.trade_name,
        legal_name=profile.legal_name,
        legal_name_kana=profile.legal_name_kana,
        corporate_number=profile.corporate_number,
        business_description=profile.business_description,
        show_representative=profile.show_representative,
        representative_name=profile.representative_name,
        department_name=profile.department_name,
        contact_person_name=profile.contact_person_name,
        postal_code=profile.postal_code,
        address=profile.address,
        address_line1=profile.address_line1,
        address_line2=profile.address_line2,
        phone=profile.phone,
        fax=profile.fax,
        email=profile.email,
        website_url=profile.website_url,
        default_customer_honorific=profile.default_customer_honorific,
        payment_terms_days=profile.payment_terms_days,
        bank_name=profile.bank_name,
        bank_branch=profile.bank_branch,
        bank_account_type=profile.bank_account_type,
        bank_account_number=profile.bank_account_number,
        bank_account_holder=profile.bank_account_holder,
        show_bank_details=profile.show_bank_details,
        logo_ref=profile.logo_ref,
        seal_ref=profile.seal_ref,
        show_stamp_box=profile.show_stamp_box,
        show_logo=profile.show_logo,
        show_seal=profile.show_seal,
        seal_text=profile.seal_text,
        is_invoice_issuer=profile.is_invoice_issuer,
        registration_number=profile.registration_number,
        show_registration_number=profile.show_registration_number,
        invoice_message=profile.invoice_message,
        receipt_message=profile.receipt_message,
        receipt_proviso=profile.receipt_proviso,
        transfer_fee_note=profile.transfer_fee_note,
        document_footer_note=profile.document_footer_note,
        rounding_mode=profile.rounding_mode,
        price_mode=profile.price_mode,
        updated_at=profile.updated_at,
    )


def _business_error(exc: SalesDocumentError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": exc.code, "message": exc.message, "details": {}},
    )


@router.get("/business-profile", response_model=BusinessProfileOut)
def get_business_profile(db: Session = Depends(get_db)) -> BusinessProfileOut:
    try:
        profile = get_or_create_profile(db, get_taxpayer(db))
    except SalesDocumentError as exc:
        raise _business_error(exc) from exc
    db.commit()
    db.refresh(profile)
    return _out(profile)


@router.patch("/business-profile", response_model=BusinessProfileOut)
def patch_business_profile(
    patch: BusinessProfilePatch,
    db: Session = Depends(get_db),
) -> BusinessProfileOut:
    try:
        profile = get_or_create_profile(db, get_taxpayer(db))
    except SalesDocumentError as exc:
        raise _business_error(exc) from exc
    data = patch.model_dump(exclude_unset=True)
    registration = data.get("registration_number", profile.registration_number)
    issuer_enabled = data.get("is_invoice_issuer", profile.is_invoice_issuer)
    if registration and not _REGISTRATION_NUMBER.fullmatch(str(registration)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_registration_number",
                "message": "登録番号はTと13桁の数字で入力してください。",
                "details": {"field": "registration_number"},
            },
        )
    corporate_number = data.get("corporate_number", profile.corporate_number)
    if corporate_number and not _CORPORATE_NUMBER.fullmatch(str(corporate_number)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_corporate_number",
                "message": "法人番号は13桁の数字で入力してください。",
                "details": {"field": "corporate_number"},
            },
        )
    if issuer_enabled and not registration:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "registration_number_required",
                "message": "適格請求書発行事業者の登録番号を入力してください。",
                "details": {"field": "registration_number"},
            },
        )
    for field_name, value in data.items():
        setattr(profile, field_name, value)
    db.commit()
    db.refresh(profile)
    return _out(profile)
