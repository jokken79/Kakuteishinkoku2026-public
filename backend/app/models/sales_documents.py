"""Modelos del dominio de documentos comerciales emitidos (売上・請求)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import (
    SalesDocumentStatus,
    SalesDocumentType,
    SalesPaymentMethod,
    SalesPriceMode,
    SalesTaxCategory,
    TaxRoundingMode,
)
from app.models.types import GUID, PortableJSON, new_uuid


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), primary_key=True, default=new_uuid)


class BusinessProfile(Base, TimestampMixin):
    """事業者情報 — identidad comercial usada al emitir documentos."""

    __tablename__ = "business_profile"
    __table_args__ = (UniqueConstraint("taxpayer_id", name="uq_business_profile_taxpayer"),)

    id: Mapped[uuid.UUID] = _pk()
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("taxpayer.id", ondelete="CASCADE"), nullable=False
    )
    trade_name: Mapped[str] = mapped_column(String(255), nullable=False, default="事業者")
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_name_kana: Mapped[str | None] = mapped_column(String(255), nullable=True)
    corporate_number: Mapped[str | None] = mapped_column(String(13), nullable=True)
    business_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    show_representative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    representative_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_person_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fax: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_customer_honorific: Mapped[str] = mapped_column(
        String(16), nullable=False, default="御中"
    )
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    bank_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bank_branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bank_account_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bank_account_holder: Mapped[str | None] = mapped_column(String(128), nullable=True)
    show_bank_details: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    logo_ref: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    seal_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    show_stamp_box: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_logo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_seal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    seal_text: Mapped[str | None] = mapped_column(String(16), nullable=True, default="領収")
    is_invoice_issuer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registration_number: Mapped[str | None] = mapped_column(String(14), nullable=True)
    show_registration_number: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    invoice_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_proviso: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transfer_fee_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_footer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    rounding_mode: Mapped[TaxRoundingMode] = mapped_column(
        String(16), nullable=False, default=TaxRoundingMode.FLOOR
    )
    price_mode: Mapped[SalesPriceMode] = mapped_column(
        String(16), nullable=False, default=SalesPriceMode.EXCLUSIVE
    )


class Customer(Base, TimestampMixin):
    """取引先 — maestro opcional de clientes."""

    __tablename__ = "customer"

    id: Mapped[uuid.UUID] = _pk()
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("taxpayer.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    honorific: Mapped[str] = mapped_column(String(16), nullable=False, default="御中")
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CatalogItem(Base, TimestampMixin):
    """品目 — producto o servicio reutilizable."""

    __tablename__ = "catalog_item"

    id: Mapped[uuid.UUID] = _pk()
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("taxpayer.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="式")
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_category: Mapped[SalesTaxCategory] = mapped_column(
        String(24), nullable=False, default=SalesTaxCategory.STANDARD_10
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SalesDocument(Base, TimestampMixin):
    """売上書類 — cabecera comun para todos los documentos comerciales."""

    __tablename__ = "sales_document"
    __table_args__ = (
        UniqueConstraint(
            "taxpayer_id", "document_type", "document_number", name="uq_sales_document_number"
        ),
        UniqueConstraint("taxpayer_id", "creation_key", name="uq_sales_document_creation_key"),
    )

    id: Mapped[uuid.UUID] = _pk()
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("taxpayer.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fiscal_year_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("fiscal_year.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("customer.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("sales_document.id", ondelete="SET NULL"), nullable=True
    )
    document_type: Mapped[SalesDocumentType] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[SalesDocumentStatus] = mapped_column(
        String(24), nullable=False, default=SalesDocumentStatus.DRAFT, index=True
    )
    document_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    creation_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_snapshot: Mapped[dict[str, object]] = mapped_column(
        PortableJSON, nullable=False, default=dict
    )
    issuer_snapshot: Mapped[dict[str, object] | None] = mapped_column(PortableJSON, nullable=True)
    subtotal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_8: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_10: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    amount_paid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rounding_mode: Mapped[TaxRoundingMode] = mapped_column(
        String(16), nullable=False, default=TaxRoundingMode.FLOOR
    )
    price_mode: Mapped[SalesPriceMode] = mapped_column(
        String(16), nullable=False, default=SalesPriceMode.EXCLUSIVE
    )
    is_qualified_invoice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lines: Mapped[list[SalesDocumentLine]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="SalesDocumentLine.position",
    )
    payments: Mapped[list[SalesPayment]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        foreign_keys="SalesPayment.document_id",
    )
    events: Mapped[list[SalesDocumentEvent]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[SalesDocumentArtifact]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class SalesDocumentLine(Base):
    """明細 — linea calculada del documento."""

    __tablename__ = "sales_document_line"

    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("sales_document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("1"))
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="式")
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_category: Mapped[SalesTaxCategory] = mapped_column(String(24), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)

    document: Mapped[SalesDocument] = relationship(back_populates="lines")


class SalesPayment(Base, TimestampMixin):
    """入金 — cobro aplicado a una factura."""

    __tablename__ = "sales_payment"
    __table_args__ = (
        UniqueConstraint("document_id", "idempotency_key", name="uq_sales_payment_idempotency"),
    )

    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("sales_document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[SalesPaymentMethod] = mapped_column(String(24), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("sales_document.id", ondelete="SET NULL"), nullable=True
    )

    document: Mapped[SalesDocument] = relationship(
        back_populates="payments", foreign_keys=[document_id]
    )


class SalesDocumentEvent(Base):
    """変更履歴 — eventos append-only del ciclo documental."""

    __tablename__ = "sales_document_event"

    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("sales_document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object] | None] = mapped_column(PortableJSON, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[SalesDocument] = relationship(back_populates="events")


class SalesDocumentArtifact(Base):
    """発行PDF — copia inmutable del artefacto entregado."""

    __tablename__ = "sales_document_artifact"
    __table_args__ = (
        UniqueConstraint("document_id", "revision", name="uq_sales_document_artifact_revision"),
    )

    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("sales_document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[SalesDocument] = relationship(back_populates="artifacts")


class SalesDocumentSequence(Base):
    """採番 — contador por contribuyente, tipo y año."""

    __tablename__ = "sales_document_sequence"
    __table_args__ = (
        UniqueConstraint(
            "taxpayer_id", "document_type", "year", name="uq_sales_document_sequence_scope"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("taxpayer.id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[SalesDocumentType] = mapped_column(String(32), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
