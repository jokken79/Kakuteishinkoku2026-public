"""API completa de 売上・請求: clientes, documentos, emisión y cobros."""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
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
    CatalogItem,
    Customer,
    SalesDocument,
    SalesDocumentArtifact,
)
from app.services.sales_documents.pdf import render_sales_document
from app.services.sales_documents.service import (
    SalesDocumentError,
    convert_document,
    customer_snapshot,
    get_or_create_profile,
    get_taxpayer,
    issue_document,
    mark_sent,
    register_payment,
    replace_lines,
    resolve_fiscal_year,
    void_document,
)

router = APIRouter(tags=["sales-documents"])


class CustomerBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    honorific: str = Field(default="御中", max_length=16)
    postal_code: str | None = Field(default=None, max_length=16)
    address: str | None = Field(default=None, max_length=512)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    is_active: bool = True


class CustomerCreate(CustomerBase):
    pass


class CustomerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    honorific: str | None = Field(default=None, max_length=16)
    postal_code: str | None = Field(default=None, max_length=16)
    address: str | None = Field(default=None, max_length=512)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    is_active: bool | None = None


class CustomerOut(CustomerBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CatalogItemBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    unit: str = Field(default="式", max_length=32)
    unit_price: int = Field(default=0, ge=0, le=100_000_000)
    tax_category: SalesTaxCategory = SalesTaxCategory.STANDARD_10
    is_active: bool = True


class CatalogItemCreate(CatalogItemBase):
    pass


class CatalogItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    unit: str | None = Field(default=None, max_length=32)
    unit_price: int | None = Field(default=None, ge=0, le=100_000_000)
    tax_category: SalesTaxCategory | None = None
    is_active: bool | None = None


class CatalogItemOut(CatalogItemBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CustomerSnapshotIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    honorific: str = Field(default="御中", max_length=16)
    postal_code: str | None = Field(default=None, max_length=16)
    address: str | None = Field(default=None, max_length=512)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)


class SalesLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=512)
    quantity: Decimal = Field(default=Decimal("1"), gt=0, max_digits=12, decimal_places=3)
    unit: str = Field(default="式", max_length=32)
    unit_price: int = Field(ge=0, le=100_000_000)
    discount_amount: int = Field(default=0, ge=0, le=100_000_000)
    tax_category: SalesTaxCategory = SalesTaxCategory.STANDARD_10


class SalesLineOut(BaseModel):
    id: uuid.UUID
    position: int
    description: str
    quantity: Decimal
    unit: str
    unit_price: int
    discount_amount: int
    tax_category: SalesTaxCategory
    amount: int


class SalesPaymentOut(BaseModel):
    id: uuid.UUID
    payment_date: date
    amount: int
    method: SalesPaymentMethod
    reference: str | None
    receipt_document_id: uuid.UUID | None
    created_at: datetime


class SalesDocumentCreate(BaseModel):
    document_type: SalesDocumentType
    customer_id: uuid.UUID | None = None
    customer: CustomerSnapshotIn | None = None
    subject: str | None = Field(default=None, max_length=255)
    issue_date: date
    due_date: date | None = None
    notes: str | None = None
    rounding_mode: TaxRoundingMode | None = None
    price_mode: SalesPriceMode | None = None
    is_qualified_invoice: bool = False
    creation_key: str | None = Field(default=None, max_length=64)
    lines: list[SalesLineIn] = Field(default_factory=list, max_length=100)


class SalesDocumentPatch(BaseModel):
    customer_id: uuid.UUID | None = None
    customer: CustomerSnapshotIn | None = None
    subject: str | None = Field(default=None, max_length=255)
    issue_date: date | None = None
    due_date: date | None = None
    notes: str | None = None
    rounding_mode: TaxRoundingMode | None = None
    price_mode: SalesPriceMode | None = None
    is_qualified_invoice: bool | None = None
    lines: list[SalesLineIn] | None = Field(default=None, max_length=100)


class SalesDocumentOut(BaseModel):
    id: uuid.UUID
    document_type: SalesDocumentType
    status: SalesDocumentStatus
    document_number: str | None
    customer_id: uuid.UUID | None
    source_document_id: uuid.UUID | None
    subject: str | None
    issue_date: date
    due_date: date | None
    notes: str | None
    customer: dict[str, object]
    subtotal: int
    tax_8: int
    tax_10: int
    total: int
    amount_paid: int
    outstanding: int
    rounding_mode: TaxRoundingMode
    price_mode: SalesPriceMode
    is_qualified_invoice: bool
    revision: int
    issued_at: datetime | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: list[SalesLineOut]
    payments: list[SalesPaymentOut]


class ConvertRequest(BaseModel):
    target_type: SalesDocumentType
    creation_key: str | None = Field(default=None, max_length=64)


class VoidRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class PaymentCreate(BaseModel):
    payment_date: date
    amount: int = Field(gt=0, le=100_000_000)
    method: SalesPaymentMethod = SalesPaymentMethod.BANK_TRANSFER
    reference: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=64)
    create_receipt: bool = True


def _business_http(exc: SalesDocumentError) -> HTTPException:
    status_code = (
        status.HTTP_409_CONFLICT
        if exc.code in {"document_locked", "document_voided", "paid_document"}
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message, "details": {}},
    )


def _customer_out(customer: Customer) -> CustomerOut:
    return CustomerOut(
        id=customer.id,
        name=customer.name,
        honorific=customer.honorific,
        postal_code=customer.postal_code,
        address=customer.address,
        contact_name=customer.contact_name,
        email=customer.email,
        phone=customer.phone,
        payment_terms_days=customer.payment_terms_days,
        is_active=customer.is_active,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
    )


def _catalog_out(item: CatalogItem) -> CatalogItemOut:
    return CatalogItemOut(
        id=item.id,
        name=item.name,
        description=item.description,
        unit=item.unit,
        unit_price=item.unit_price,
        tax_category=item.tax_category,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _document_out(document: SalesDocument) -> SalesDocumentOut:
    return SalesDocumentOut(
        id=document.id,
        document_type=document.document_type,
        status=document.status,
        document_number=document.document_number,
        customer_id=document.customer_id,
        source_document_id=document.source_document_id,
        subject=document.subject,
        issue_date=document.issue_date,
        due_date=document.due_date,
        notes=document.notes,
        customer=document.customer_snapshot,
        subtotal=document.subtotal,
        tax_8=document.tax_8,
        tax_10=document.tax_10,
        total=document.total,
        amount_paid=document.amount_paid,
        outstanding=max(0, document.total - document.amount_paid),
        rounding_mode=document.rounding_mode,
        price_mode=document.price_mode,
        is_qualified_invoice=document.is_qualified_invoice,
        revision=document.revision,
        issued_at=document.issued_at,
        sent_at=document.sent_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
        lines=[
            SalesLineOut(
                id=line.id,
                position=line.position,
                description=line.description,
                quantity=line.quantity,
                unit=line.unit,
                unit_price=line.unit_price,
                discount_amount=line.discount_amount,
                tax_category=line.tax_category,
                amount=line.amount,
            )
            for line in document.lines
        ],
        payments=[
            SalesPaymentOut(
                id=payment.id,
                payment_date=payment.payment_date,
                amount=payment.amount,
                method=payment.method,
                reference=payment.reference,
                receipt_document_id=payment.receipt_document_id,
                created_at=payment.created_at,
            )
            for payment in sorted(document.payments, key=lambda item: item.payment_date)
        ],
    )


def _document_or_404(db: Session, document_id: uuid.UUID) -> SalesDocument:
    document = db.scalar(
        select(SalesDocument)
        .options(selectinload(SalesDocument.lines), selectinload(SalesDocument.payments))
        .where(SalesDocument.id == document_id)
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "書類が見つかりませんでした。", "details": {}},
        )
    return document


def _customer_or_404(db: Session, customer_id: uuid.UUID) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": "取引先が見つかりませんでした。",
                "details": {},
            },
        )
    return customer


def _line_tuples(
    lines: list[SalesLineIn],
) -> list[tuple[str, Decimal, str, int, int, SalesTaxCategory]]:
    return [
        (
            line.description,
            line.quantity,
            line.unit,
            line.unit_price,
            line.discount_amount,
            line.tax_category,
        )
        for line in lines
    ]


def _default_notes(profile: BusinessProfile, document_type: SalesDocumentType) -> str | None:
    if document_type == SalesDocumentType.RECEIPT:
        return profile.receipt_message or "上記金額を正に領収いたしました。"
    if document_type in {
        SalesDocumentType.INVOICE,
        SalesDocumentType.CONSOLIDATED_INVOICE,
        SalesDocumentType.CORRECTED_INVOICE,
    }:
        return profile.invoice_message or profile.transfer_fee_note
    return None


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(db: Session = Depends(get_db)) -> list[CustomerOut]:
    taxpayer = get_taxpayer(db)
    customers = db.scalars(
        select(Customer).where(Customer.taxpayer_id == taxpayer.id).order_by(Customer.name)
    ).all()
    return [_customer_out(customer) for customer in customers]


@router.post("/customers", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)) -> CustomerOut:
    taxpayer = get_taxpayer(db)
    customer = Customer(taxpayer_id=taxpayer.id, **payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return _customer_out(customer)


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def patch_customer(
    customer_id: uuid.UUID,
    patch: CustomerPatch,
    db: Session = Depends(get_db),
) -> CustomerOut:
    customer = _customer_or_404(db, customer_id)
    for field_name, value in patch.model_dump(exclude_unset=True).items():
        setattr(customer, field_name, value)
    db.commit()
    db.refresh(customer)
    return _customer_out(customer)


@router.get("/catalog-items", response_model=list[CatalogItemOut])
def list_catalog_items(db: Session = Depends(get_db)) -> list[CatalogItemOut]:
    taxpayer = get_taxpayer(db)
    items = db.scalars(
        select(CatalogItem).where(CatalogItem.taxpayer_id == taxpayer.id).order_by(CatalogItem.name)
    ).all()
    return [_catalog_out(item) for item in items]


@router.post("/catalog-items", response_model=CatalogItemOut, status_code=status.HTTP_201_CREATED)
def create_catalog_item(
    payload: CatalogItemCreate,
    db: Session = Depends(get_db),
) -> CatalogItemOut:
    taxpayer = get_taxpayer(db)
    item = CatalogItem(taxpayer_id=taxpayer.id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _catalog_out(item)


@router.patch("/catalog-items/{item_id}", response_model=CatalogItemOut)
def patch_catalog_item(
    item_id: uuid.UUID,
    patch: CatalogItemPatch,
    db: Session = Depends(get_db),
) -> CatalogItemOut:
    item = db.get(CatalogItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="品目が見つかりませんでした。")
    for field_name, value in patch.model_dump(exclude_unset=True).items():
        setattr(item, field_name, value)
    db.commit()
    db.refresh(item)
    return _catalog_out(item)


@router.get("/sales-documents", response_model=list[SalesDocumentOut])
def list_sales_documents(
    document_type: SalesDocumentType | None = None,
    document_status: SalesDocumentStatus | None = Query(default=None, alias="status"),
    year: int | None = Query(default=None, ge=1989, le=2100),
    db: Session = Depends(get_db),
) -> list[SalesDocumentOut]:
    taxpayer = get_taxpayer(db)
    statement = (
        select(SalesDocument)
        .options(selectinload(SalesDocument.lines), selectinload(SalesDocument.payments))
        .where(SalesDocument.taxpayer_id == taxpayer.id)
        .order_by(SalesDocument.issue_date.desc(), SalesDocument.created_at.desc())
    )
    if document_type:
        statement = statement.where(SalesDocument.document_type == document_type)
    if document_status:
        statement = statement.where(SalesDocument.status == document_status)
    documents = list(db.scalars(statement).all())
    if year is not None:
        documents = [document for document in documents if document.issue_date.year == year]
    return [_document_out(document) for document in documents]


@router.post(
    "/sales-documents",
    response_model=SalesDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_sales_document(
    payload: SalesDocumentCreate,
    db: Session = Depends(get_db),
) -> SalesDocumentOut:
    taxpayer = get_taxpayer(db)
    if payload.creation_key:
        existing = db.scalar(
            select(SalesDocument)
            .options(selectinload(SalesDocument.lines), selectinload(SalesDocument.payments))
            .where(
                SalesDocument.taxpayer_id == taxpayer.id,
                SalesDocument.creation_key == payload.creation_key,
            )
        )
        if existing:
            return _document_out(existing)
    profile: BusinessProfile = get_or_create_profile(db, taxpayer)
    customer_id = payload.customer_id
    if customer_id:
        customer_data = customer_snapshot(_customer_or_404(db, customer_id))
    elif payload.customer:
        customer_data = payload.customer.model_dump()
    else:
        customer_data = {"name": "", "honorific": profile.default_customer_honorific}
    if not customer_data.get("honorific"):
        customer_data["honorific"] = profile.default_customer_honorific
    fiscal_year = resolve_fiscal_year(db, taxpayer.id, payload.issue_date.year)
    due_date = payload.due_date
    if due_date is None and payload.document_type in {
        SalesDocumentType.INVOICE,
        SalesDocumentType.CONSOLIDATED_INVOICE,
        SalesDocumentType.CORRECTED_INVOICE,
    }:
        due_date = payload.issue_date + timedelta(days=profile.payment_terms_days)
    document = SalesDocument(
        taxpayer_id=taxpayer.id,
        fiscal_year_id=fiscal_year.id if fiscal_year else None,
        customer_id=customer_id,
        document_type=payload.document_type,
        status=SalesDocumentStatus.DRAFT,
        creation_key=payload.creation_key,
        subject=payload.subject,
        issue_date=payload.issue_date,
        due_date=due_date,
        notes=(
            payload.notes
            if payload.notes is not None
            else _default_notes(profile, payload.document_type)
        ),
        customer_snapshot=customer_data,
        rounding_mode=payload.rounding_mode or profile.rounding_mode,
        price_mode=payload.price_mode or profile.price_mode,
        is_qualified_invoice=payload.is_qualified_invoice,
    )
    db.add(document)
    try:
        replace_lines(document, _line_tuples(payload.lines))
    except (SalesDocumentError, ValueError) as exc:
        db.rollback()
        if isinstance(exc, SalesDocumentError):
            raise _business_http(exc) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _document_out(_document_or_404(db, document.id))


@router.get("/sales-documents/{document_id}", response_model=SalesDocumentOut)
def get_sales_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> SalesDocumentOut:
    return _document_out(_document_or_404(db, document_id))


@router.patch("/sales-documents/{document_id}", response_model=SalesDocumentOut)
def patch_sales_document(
    document_id: uuid.UUID,
    patch: SalesDocumentPatch,
    db: Session = Depends(get_db),
) -> SalesDocumentOut:
    document = _document_or_404(db, document_id)
    if document.status != SalesDocumentStatus.DRAFT:
        raise _business_http(
            SalesDocumentError("document_locked", "発行済みの書類は編集できません。")
        )
    data = patch.model_dump(exclude_unset=True, exclude={"lines", "customer"})
    if "customer_id" in data and data["customer_id"]:
        selected_customer = _customer_or_404(db, data["customer_id"])
        document.customer_snapshot = customer_snapshot(selected_customer)
    if patch.customer is not None:
        document.customer_snapshot = patch.customer.model_dump()
        document.customer_id = None
    for field_name, value in data.items():
        setattr(document, field_name, value)
    if patch.issue_date:
        fiscal_year = resolve_fiscal_year(db, document.taxpayer_id, patch.issue_date.year)
        document.fiscal_year_id = fiscal_year.id if fiscal_year else None
    if patch.lines is not None:
        try:
            replace_lines(document, _line_tuples(patch.lines))
        except (SalesDocumentError, ValueError) as exc:
            db.rollback()
            if isinstance(exc, SalesDocumentError):
                raise _business_http(exc) from exc
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _document_out(_document_or_404(db, document.id))


@router.post("/sales-documents/{document_id}/issue", response_model=SalesDocumentOut)
def issue_sales_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> SalesDocumentOut:
    document = _document_or_404(db, document_id)
    try:
        issue_document(db, document)
    except SalesDocumentError as exc:
        db.rollback()
        raise _business_http(exc) from exc
    db.commit()
    return _document_out(_document_or_404(db, document.id))


@router.post("/sales-documents/{document_id}/convert", response_model=SalesDocumentOut)
def convert_sales_document(
    document_id: uuid.UUID,
    payload: ConvertRequest,
    db: Session = Depends(get_db),
) -> SalesDocumentOut:
    source = _document_or_404(db, document_id)
    converted = convert_document(db, source, payload.target_type, creation_key=payload.creation_key)
    db.commit()
    return _document_out(_document_or_404(db, converted.id))


@router.post("/sales-documents/{document_id}/duplicate", response_model=SalesDocumentOut)
def duplicate_sales_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> SalesDocumentOut:
    source = _document_or_404(db, document_id)
    duplicate = convert_document(db, source, source.document_type)
    duplicate.source_document_id = None
    db.commit()
    return _document_out(_document_or_404(db, duplicate.id))


@router.post("/sales-documents/{document_id}/send", response_model=SalesDocumentOut)
def send_sales_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> SalesDocumentOut:
    document = _document_or_404(db, document_id)
    try:
        mark_sent(db, document)
    except SalesDocumentError as exc:
        raise _business_http(exc) from exc
    db.commit()
    return _document_out(_document_or_404(db, document.id))


@router.post("/sales-documents/{document_id}/void", response_model=SalesDocumentOut)
def void_sales_document(
    document_id: uuid.UUID,
    payload: VoidRequest,
    db: Session = Depends(get_db),
) -> SalesDocumentOut:
    document = _document_or_404(db, document_id)
    try:
        void_document(db, document, payload.reason)
    except SalesDocumentError as exc:
        raise _business_http(exc) from exc
    db.commit()
    return _document_out(_document_or_404(db, document.id))


@router.post(
    "/sales-documents/{document_id}/payments",
    response_model=SalesPaymentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_sales_payment(
    document_id: uuid.UUID,
    payload: PaymentCreate,
    db: Session = Depends(get_db),
) -> SalesPaymentOut:
    document = _document_or_404(db, document_id)
    try:
        payment = register_payment(
            db,
            document,
            payment_date=payload.payment_date,
            amount=payload.amount,
            method=payload.method,
            reference=payload.reference,
            idempotency_key=payload.idempotency_key,
            create_receipt=payload.create_receipt,
        )
    except SalesDocumentError as exc:
        db.rollback()
        raise _business_http(exc) from exc
    db.commit()
    db.refresh(payment)
    return SalesPaymentOut(
        id=payment.id,
        payment_date=payment.payment_date,
        amount=payment.amount,
        method=payment.method,
        reference=payment.reference,
        receipt_document_id=payment.receipt_document_id,
        created_at=payment.created_at,
    )


@router.get("/sales-documents/{document_id}/pdf")
def sales_document_pdf(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    document = _document_or_404(db, document_id)
    artifact: SalesDocumentArtifact | None = None
    if document.status != SalesDocumentStatus.DRAFT:
        artifact = db.scalar(
            select(SalesDocumentArtifact).where(
                SalesDocumentArtifact.document_id == document.id,
                SalesDocumentArtifact.revision == document.revision,
            )
        )
    content = artifact.content if artifact else render_sales_document(document)
    filename = artifact.filename if artifact else f"draft-{document.id}.pdf"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
