"""Modelos del dominio fiscal (SQLAlchemy 2.0, estilo `Mapped[]`).

Implementa las entidades del plan 01: Taxpayer, FiscalYear, Account,
Transaction, JournalEntry/JournalLine, Evidence, Deduction, IncomeSource,
FixedAsset, FilingDraft y AuditLog.

Convenciones:
- Todos los montos son enteros (yenes, sin decimales).
- PK uuid via `GUID` portable; JSON via `PortableJSON`.
- `my_number` se marca como sensible: nunca debe loguearse ni exponerse en
  serializaciones por defecto (ver `Taxpayer.__repr__`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import (
    AccountCategory,
    ConsumptionMethod,
    DeductionType,
    DepreciationMethod,
    FilingDraftStatus,
    FilingType,
    FiscalYearStatus,
    HouseholdCategory,
    IncomeType,
    JournalSide,
    TransactionSource,
    TransactionStatus,
)
from app.models.types import GUID, PortableJSON, new_uuid


def _pk() -> Mapped[uuid.UUID]:
    """Columna PK uuid con default generado en Python.

    Returns:
        Columna mapeada como PK uuid.
    """
    return mapped_column(GUID(), primary_key=True, default=new_uuid)


class Taxpayer(Base, TimestampMixin):
    """納税者 — contribuyente (persona fisica / 個人事業主)."""

    __tablename__ = "taxpayer"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_kana: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # マイナンバー — DATO SENSIBLE: almacenar cifrado, nunca loguear.
    my_number: Mapped[str | None] = mapped_column(String(512), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    filing_type: Mapped[FilingType] = mapped_column(
        String(16), nullable=False, default=FilingType.AOIRO_65
    )
    is_taxable_consumption: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    consumption_method: Mapped[ConsumptionMethod | None] = mapped_column(
        String(16), nullable=True
    )
    # 事業区分 (1〜6) del 簡易課税 — みなし仕入率. Solo relevante si consumption_method
    # es 簡易課税; None para 本則/2割特例 o 免税.
    consumption_business_category: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    business_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 税務署 (提出先) — clave estable del 税務署 de presentación (ej. "tsushima").
    # None => no determinada (ver `services/forms/tax_office.py`).
    filing_office: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Onboarding completado: ``False`` para un usuario nuevo (muestra el flujo
    # guiado), ``True`` tras completar la configuración inicial. El seed de demo
    # lo marca ``True`` para no romper el escenario existente.
    onboarded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    fiscal_years: Mapped[list[FiscalYear]] = relationship(
        back_populates="taxpayer",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """Repr sin exponer `my_number` (dato sensible)."""
        return f"<Taxpayer id={self.id} name={self.name!r}>"


class FiscalYear(Base):
    """年度 — ejercicio fiscal de un contribuyente."""

    __tablename__ = "fiscal_year"

    id: Mapped[uuid.UUID] = _pk()
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("taxpayer.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    rules_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[FiscalYearStatus] = mapped_column(
        String(16), nullable=False, default=FiscalYearStatus.OPEN
    )
    estimated_prepayment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NULL conserva el valor heredado del perfil sin atribuirlo al ejercicio.
    filing_type_override: Mapped[FilingType | None] = mapped_column(String(16), nullable=True)

    taxpayer: Mapped[Taxpayer] = relationship(back_populates="fiscal_years")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="fiscal_year", cascade="all, delete-orphan"
    )
    journal_entries: Mapped[list[JournalEntry]] = relationship(
        back_populates="fiscal_year", cascade="all, delete-orphan"
    )
    deductions: Mapped[list[Deduction]] = relationship(
        back_populates="fiscal_year", cascade="all, delete-orphan"
    )
    income_sources: Mapped[list[IncomeSource]] = relationship(
        back_populates="fiscal_year", cascade="all, delete-orphan"
    )
    filing_drafts: Mapped[list[FilingDraft]] = relationship(
        back_populates="fiscal_year", cascade="all, delete-orphan"
    )
    opening_balances: Mapped[list[OpeningBalance]] = relationship(
        back_populates="fiscal_year",
        cascade="all, delete-orphan",
        order_by="OpeningBalance.account_id",
    )

    def __repr__(self) -> str:
        return f"<FiscalYear id={self.id} year={self.year} status={self.status}>"


class Account(Base):
    """勘定科目 — cuenta contable."""

    __tablename__ = "account"

    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[AccountCategory] = mapped_column(String(16), nullable=False)
    tax_form_line: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    journal_lines: Mapped[list[JournalLine]] = relationship(back_populates="account")
    opening_balances: Mapped[list[OpeningBalance]] = relationship(back_populates="account")

    def __repr__(self) -> str:
        return f"<Account code={self.code} name={self.name!r} category={self.category}>"


class OpeningBalance(Base, TimestampMixin):
    """期首残高 — saldo manual al iniciar un 年度.

    Es la fuente editable del usuario para los saldos iniciales. La app genera
    además un `JournalEntry` marcado como ``created_by='opening_balance'`` para
    que el 試算表 y 貸借対照表 reflejen estos importes sin una ruta contable
    paralela.
    """

    __tablename__ = "opening_balance"
    __table_args__ = (
        UniqueConstraint("fiscal_year_id", "account_id", name="uq_opening_balance_year_account"),
    )

    id: Mapped[uuid.UUID] = _pk()
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fiscal_year.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("account.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    fiscal_year: Mapped[FiscalYear] = relationship(back_populates="opening_balances")
    account: Mapped[Account] = relationship(back_populates="opening_balances")

    def __repr__(self) -> str:
        return f"<OpeningBalance account_id={self.account_id} amount={self.amount}>"


class Evidence(Base):
    """領収書・証明書 — comprobante/recibo (電帳法)."""

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = _pk()
    file_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    hash: Mapped[str] = mapped_column(String(128), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    idx_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    idx_amount: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    idx_vendor: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    retention_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    transaction: Mapped[Transaction | None] = relationship(back_populates="evidence")

    def __repr__(self) -> str:
        return f"<Evidence id={self.id} vendor={self.idx_vendor!r} amount={self.idx_amount}>"


class Transaction(Base, TimestampMixin):
    """取引 — transaccion cruda (recibo/CSV/manual/banco)."""

    __tablename__ = "transaction"

    id: Mapped[uuid.UUID] = _pk()
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fiscal_year.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[TransactionSource] = mapped_column(String(16), nullable=False)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )
    registration_number: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_qualified_invoice: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(
        String(16), nullable=False, default=TransactionStatus.PENDING
    )
    tax_lines: Mapped[list[dict[str, object]] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    business_allocation: Mapped[dict[str, object] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    # 勘定科目 sugerido/elegido para el gasto (editable en la bandeja de 仕訳).
    account_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Confianza por campo del OCR (date/vendor/total/...): guia "que revisar".
    field_confidences: Mapped[dict[str, object] | None] = mapped_column(
        PortableJSON, nullable=True
    )

    fiscal_year: Mapped[FiscalYear] = relationship(back_populates="transactions")
    evidence: Mapped[Evidence | None] = relationship(back_populates="transaction")
    journal_entry: Mapped[JournalEntry | None] = relationship(
        back_populates="transaction", uselist=False
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} vendor={self.vendor!r} "
            f"total={self.total_amount} status={self.status}>"
        )


class JournalEntry(Base):
    """仕訳 — asiento contable (cabecera)."""

    __tablename__ = "journal_entry"

    id: Mapped[uuid.UUID] = _pk()
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fiscal_year.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 摘要
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("transaction.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    fiscal_year: Mapped[FiscalYear] = relationship(back_populates="journal_entries")
    transaction: Mapped[Transaction | None] = relationship(back_populates="journal_entry")
    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="JournalLine.side",
    )

    def __repr__(self) -> str:
        return f"<JournalEntry id={self.id} date={self.date} lines={len(self.lines)}>"


class JournalLine(Base):
    """仕訳明細 — linea de asiento (借方/貸方)."""

    __tablename__ = "journal_line"

    id: Mapped[uuid.UUID] = _pk()
    entry_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("journal_entry.id", ondelete="CASCADE"), nullable=False
    )
    side: Mapped[JournalSide] = mapped_column(String(8), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("account.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")
    account: Mapped[Account] = relationship(back_populates="journal_lines")

    def __repr__(self) -> str:
        return (
            f"<JournalLine side={self.side} account_id={self.account_id} "
            f"amount={self.amount}>"
        )


class Deduction(Base):
    """控除 — deduccion (所得控除), origen del wizard."""

    __tablename__ = "deduction"

    id: Mapped[uuid.UUID] = _pk()
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fiscal_year.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[DeductionType] = mapped_column(String(24), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta: Mapped[dict[str, object] | None] = mapped_column(PortableJSON, nullable=True)

    fiscal_year: Mapped[FiscalYear] = relationship(back_populates="deductions")

    def __repr__(self) -> str:
        return f"<Deduction type={self.type} amount={self.amount}>"


class IncomeSource(Base):
    """所得 — fuente de ingreso por tipo."""

    __tablename__ = "income_source"

    id: Mapped[uuid.UUID] = _pk()
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fiscal_year.id", ondelete="CASCADE"), nullable=False
    )
    income_type: Mapped[IncomeType] = mapped_column(String(16), nullable=False)
    gross: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    withholding: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 源泉徴収
    meta: Mapped[dict[str, object] | None] = mapped_column(PortableJSON, nullable=True)

    fiscal_year: Mapped[FiscalYear] = relationship(back_populates="income_sources")

    def __repr__(self) -> str:
        return f"<IncomeSource type={self.income_type} gross={self.gross}>"


class FixedAsset(Base):
    """固定資産 — activo fijo (減価償却)."""

    __tablename__ = "fixed_asset"

    id: Mapped[uuid.UUID] = _pk()
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fiscal_year.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[DepreciationMethod] = mapped_column(
        String(16), nullable=False, default=DepreciationMethod.TEIGAKU
    )
    useful_life: Mapped[int] = mapped_column(Integer, nullable=False)
    accumulated_depreciation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    def __repr__(self) -> str:
        return f"<FixedAsset name={self.name!r} cost={self.cost}>"


class FilingDraft(Base, TimestampMixin):
    """申告書ドラフト — borrador del formulario de declaracion."""

    __tablename__ = "filing_draft"

    id: Mapped[uuid.UUID] = _pk()
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fiscal_year.id", ondelete="CASCADE"), nullable=False
    )
    computed: Mapped[dict[str, object] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    pdf_refs: Mapped[dict[str, object] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    xtx_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    csv_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[FilingDraftStatus] = mapped_column(
        String(16), nullable=False, default=FilingDraftStatus.DRAFT
    )

    fiscal_year: Mapped[FiscalYear] = relationship(back_populates="filing_drafts")

    def __repr__(self) -> str:
        return f"<FilingDraft id={self.id} status={self.status}>"


class PastFiling(Base, TimestampMixin):
    """過去の申告 — declaracion de 確定申告 de un anio anterior (archivo histórico).

    "Dropbox inteligente": el owner sube el PDF de su 申告書 de un ejercicio
    anterior y la app lo archiva (PDF original en disco + hash + indices) e
    intenta extraer los montos clave por texto (所得/納付額/還付額/税務署). Sirve
    para consulta histórica y comparación año a año.

    電子帳簿保存法: el PDF original se conserva indexado por al menos 7 años.
    Los campos extraidos son nullable: si el parser no los detecta con
    confianza, quedan en ``None`` y el usuario los completa a mano (nunca se
    inventan montos).
    """

    __tablename__ = "past_filing"

    id: Mapped[uuid.UUID] = _pk()
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("taxpayer.id", ondelete="CASCADE"), nullable=False
    )
    # 年度 gregoriano (ej. 2024 == 令和6年分). No es FK a fiscal_year: el archivo
    # histórico puede cubrir años sin 年度 abierto en la app.
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Ruta en disco del PDF original archivado (data/past_filings/<hash>.pdf).
    file_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    # sha256 del PDF: idempotencia (no duplicar el mismo archivo) + integridad.
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Nombre original del archivo subido (para mostrarlo/descargarlo).
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # --- Campos extraidos del PDF (nullable: el usuario los corrige) ---------
    total_income: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 所得金額
    tax_paid: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 納付税額
    tax_refund: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 還付金額
    tax_office: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 税務署
    # Texto crudo extraido del PDF (para re-parsear/auditar; no se muestra).
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'auto' (extraido por el parser) | 'manual' (editado por el usuario).
    extraction_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="auto"
    )

    taxpayer: Mapped[Taxpayer] = relationship()

    def __repr__(self) -> str:
        return f"<PastFiling year={self.year} income={self.total_income}>"


class HouseholdExpense(Base, TimestampMixin):
    """家計簿 — gasto PERSONAL (NO fiscal, NO entra a la declaración).

    Módulo 100% aditivo: trackea gastos del hogar/personales que NO van al
    仕訳 ni al cálculo del impuesto. No tiene FK a `fiscal_year` ni a
    `taxpayer` a propósito — es un libro de gastos independiente de la lógica
    contable/fiscal del negocio. Se filtra por mes/año desde el campo `date`.
    """

    __tablename__ = "household_expense"

    id: Mapped[uuid.UUID] = _pk()
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # yenes, entero
    category: Mapped[HouseholdCategory] = mapped_column(String(16), nullable=False)
    memo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<HouseholdExpense date={self.date} amount={self.amount} "
            f"category={self.category}>"
        )


class AuditLog(Base):
    """監査ログ — registro de auditoria INMUTABLE (電帳法 真実性).

    Esta tabla es append-only: nunca se debe actualizar ni borrar una fila.
    Se modela como entidad sin `updated_at` para reflejarlo.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _pk()
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before: Mapped[dict[str, object] | None] = mapped_column(PortableJSON, nullable=True)
    after: Mapped[dict[str, object] | None] = mapped_column(PortableJSON, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog entity={self.entity} action={self.action} at={self.at}>"


class VendorAccountRule(Base, TimestampMixin):
    """取引先ルール — regla aprendida 取引先 -> 勘定科目.

    Se aprende sola: cada vez que el usuario confirma un recibo (aceptando o
    corrigiendo el 科目 propuesto), se refuerza la regla del 取引先. El OCR de la
    proxima foto de esa misma tienda ya propone el 科目 correcto.

    `vendor_key` es el nombre del 取引先 normalizado (NFKC, minusculas, sin
    espacios ni sufijos societarios), asi "セブン-イレブン 渋谷店" y
    "セブンイレブン" caen en la misma regla.
    """

    __tablename__ = "vendor_account_rule"
    __table_args__ = (UniqueConstraint("vendor_key", name="uq_vendor_account_rule_key"),)

    id: Mapped[uuid.UUID] = _pk()
    vendor_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Ultimo nombre visto tal cual venia del OCR (para mostrarlo en la UI).
    vendor_sample: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_code: Mapped[str] = mapped_column(String(32), nullable=False)
    # Veces que el usuario confirmo este 科目 para este 取引先.
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<VendorAccountRule key={self.vendor_key!r} "
            f"account={self.account_code} hits={self.hits}>"
        )
