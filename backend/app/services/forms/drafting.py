"""Ensamblado del 確定申告 (FilingDraft) — Fase 3B-2.

Orquesta el calculo completo de la declaracion a partir de los datos reales del
年度:

    取引 confirmados  ─┐
                       ├─► 仕訳 (materializados) ─► 総勘定元帳 ─► 試算表
    売上 del perfil ──┘                                 │
                                                        ▼
                              損益計算書 (PL) ─► 事業所得 = PL − 青色特別控除
                                                        │
    控除 registradas ──────────────────────────────────┤
                                                        ▼
                              calculate() ─► 課税所得 ─► 所得税 ─► 納付額/還付金

El 事業所得 se deriva del motor contable (`app.domain.accounting`): los gastos
confirmados se convierten en asientos (gasto al 借方, 事業主借 al 貸方, el mismo
patron del pipeline OCR) y se suma un asiento de 売上 del perfil del owner para
que el PL refleje el ingreso. El resultado del calculo fiscal usa exactamente el
mismo `calculate()` que `/tax/calculate`, de modo que el 納付額 cuadra.

El draft NO inventa numeros: cada monto sale del motor contable, de la
calculadora pura, o de las `IncomeSource` que el owner ingresa (売上, 源泉徴収,
給与…). Antes el 売上 y el 源泉 vivian HARDCODEADOS aca (¥6,800,000 / ¥410,000);
ahora son DATOS EDITABLES leidos de `IncomeSource`. Si no hay ninguna cargada,
los montos son 0 (no el hardcode).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.accounting import (
    BalanceSheet,
    IncomeStatement,
    Ledger,
    TrialBalance,
    balance_sheet,
    build_ledger,
    income_statement,
    post_entry,
    trial_balance,
)
from app.domain.mixed_expenses import transaction_allocation
from app.domain.tax.deduction_service import deductions_to_input, total_tax_credits
from app.domain.tax.income_source_service import (
    extra_income_inputs,
    jigyo_sales_revenue,
    total_withholding,
)
from app.domain.tax.income_tax import calculate
from app.domain.tax.resident_tax import ResidentTaxResult, calculate_resident_tax
from app.domain.tax.schemas import (
    IncomeInput,
    TaxCalculationInput,
    TaxCalculationResult,
    WithholdingInput,
)
from app.models.entities import (
    Account,
    Deduction,
    FilingDraft,
    FiscalYear,
    IncomeSource,
    JournalEntry,
    JournalLine,
    Transaction,
)
from app.models.enums import (
    FilingType,
    FiscalYearStatus,
    JournalSide,
    TransactionStatus,
)
from app.services.tax_rules import TaxRules, load_tax_rules

logger = logging.getLogger(__name__)

PROJECTION_CREATED_BY = "filing_projection_v1"


class UnidentifiedJournalEntriesError(Exception):
    """Hay asientos sin procedencia comprobable que no deben sobrescribirse."""


class ClosedYearWithoutDraftError(Exception):
    """Un ejercicio bloqueado no tiene un borrador previo que consultar."""

# El 売上 y el 源泉 reales se leen de `IncomeSource` (datos editables del owner).
# Los valores del escenario demo (売上 6.8M / 源泉 410k) viven ahora en
# `app.seed.dev_seed` (DEMO_SALES_REVENUE / DEMO_WITHHOLDING_TAX) — única fuente.
# El cálculo del draft NO hardcodea montos: sin `IncomeSource`, valen 0.

# 勘定科目 usados al materializar los asientos del draft.
ACCOUNT_SALES = "401"  # 売上高 (収益)
ACCOUNT_OWNER_CONTRA = "312"  # 事業主借 (資本) — contrapartida de gastos del titular
ACCOUNT_OWNER_DRAWING = "311"  # 事業主貸 — contrapartida del 売上 cobrado por el titular

# 青色申告特別控除 por modalidad (se resuelve contra el JSON del anio).
_AOIRO_KEY: dict[str, str] = {
    FilingType.AOIRO_65.value: "double_entry_etax",
    FilingType.AOIRO_55.value: "double_entry_paper",
    FilingType.AOIRO_10.value: "simple",
    FilingType.SHIROIRO.value: "simple",  # 白色 no tiene 特別控除; se trata como 0 abajo.
}


def _mask_my_number(my_number: str | None) -> str | None:
    """Enmascara la マイナンバー dejando solo los últimos 4 dígitos.

    El 個人番号 es dato sensible (research / security.md): nunca se expone
    completo en pantallas/PDF intermedios. El formulario final que el usuario
    imprime para 郵送 sí lleva el número completo, pero esta proyección lo
    enmascara por defecto para revisión segura.

    Args:
        my_number: マイナンバー en claro (12 dígitos) o ``None``.

    Returns:
        Cadena enmascarada (``"********1234"``) o ``None`` si no hay número.
    """
    if not my_number:
        return None
    digits = "".join(ch for ch in my_number if ch.isdigit())
    if len(digits) < 4:
        return "*" * len(digits) if digits else None
    return "*" * (len(digits) - 4) + digits[-4:]


@dataclass
class TaxpayerProfile:
    """Datos del 納税者 que van en el encabezado del 第一表.

    Espejo de los campos del modelo `Taxpayer` necesarios para el encabezado
    oficial (納税地, 氏名/フリガナ, 個人番号 enmascarado, 生年月日, 職業).
    La `my_number` se almacena YA enmascarada (ver `_mask_my_number`).

    Args:
        name: 氏名.
        name_kana: フリガナ.
        postal_code: 郵便番号 del 納税地 (sin 〒).
        address: 住所 del 納税地 (愛知県津島市…).
        my_number_masked: 個人番号 enmascarado (últimos 4) o ``None``.
        birth_date_label: 生年月日 (令和/平成/昭和 era + Y/M/D) o ``None``.
        occupation: 職業.
        filing_office_key: Clave del 税務署 de presentación, o ``None``.
    """

    name: str
    name_kana: str | None
    postal_code: str | None
    address: str | None
    my_number_masked: str | None
    birth_date_label: str | None
    occupation: str | None
    filing_office_key: str | None


def _era_birth_date(birth: date | None) -> str | None:
    """Formatea una fecha de nacimiento con era japonesa (昭和/平成/令和).

    Args:
        birth: Fecha de nacimiento o ``None``.

    Returns:
        Etiqueta ``"昭和60年1月2日"`` (etc.) o ``None`` si no hay fecha.
    """
    if birth is None:
        return None
    # Límites de era (inicio inclusivo). 西暦 → 和暦 (solo eras modernas).
    if birth >= date(2019, 5, 1):
        era, base = "令和", 2018
    elif birth >= date(1989, 1, 8):
        era, base = "平成", 1988
    elif birth >= date(1926, 12, 25):
        era, base = "昭和", 1925
    else:
        era, base = "大正", 1911
    return f"{era}{birth.year - base}年{birth.month}月{birth.day}日"


@dataclass
class FilingChecklistItem:
    """Un item de la lista de prontitud del 確定申告.

    Args:
        key: Identificador estable (en ingles).
        label: Texto en japones para la UI.
        done: ``True`` si el paso esta cumplido.
        detail: Detalle corto (ej. "未確認 3件").
    """

    key: str
    label: str
    done: bool
    detail: str | None = None


@dataclass
class FilingDraftResult:
    """Resumen estructurado completo del 確定申告 (todos los numeros).

    Args:
        draft_id: Id del `FilingDraft` persistido.
        year: 年度.
        filing_type: Modalidad de declaracion.
        taxpayer_name: Nombre del contribuyente.
        income_statement: 損益計算書 del motor contable.
        balance_sheet: 貸借対照表 del motor contable.
        aoiro_deduction: 青色申告特別控除 aplicado.
        business_income: 事業所得 = PL.net_income − aoiro_deduction (>= 0).
        sales_revenue: 売上(収入)金額 usado.
        confirmed_count: Nro de 取引 confirmados que entraron.
        pending_count: Nro de 取引 pending (avisar al usuario).
        confirmed_expense_total: Σ gastos confirmados.
        tax: Resultado completo del calculo fiscal (cuadra con /tax/calculate).
        resident_tax: Estimacion del 住民税 (impuesto de residencia, pago futuro).
        deductions: 控除 registradas (para el detalle "que entro").
        checklist: Lista de prontitud.
    """

    draft_id: uuid.UUID
    year: int
    filing_type: str
    taxpayer_name: str
    income_statement: IncomeStatement
    balance_sheet: BalanceSheet
    aoiro_deduction: int
    business_income: int
    sales_revenue: int
    confirmed_count: int
    pending_count: int
    confirmed_expense_total: int
    tax: TaxCalculationResult
    resident_tax: ResidentTaxResult
    salary_revenue: int = 0
    taxpayer_profile: TaxpayerProfile | None = None
    deductions: list[Deduction] = field(default_factory=list)
    checklist: list[FilingChecklistItem] = field(default_factory=list)


def _accounts_by_code(session: Session) -> dict[str, Account]:
    """Devuelve un mapa ``{code: Account}`` de todas las cuentas.

    Args:
        session: Sesion de SQLAlchemy.

    Returns:
        Mapa de codigo a cuenta.
    """
    return {a.code: a for a in session.scalars(select(Account)).all()}


def _aoiro_deduction(filing_type: str, business_pl: int, rules: TaxRules) -> int:
    """Calcula el 青色申告特別控除 aplicable (acotado al resultado del PL).

    El 特別控除 no puede exceder el 所得 antes de aplicarlo (no genera perdida).
    白色 no tiene 特別控除 (=> 0).

    Args:
        filing_type: Modalidad de declaracion.
        business_pl: 所得 del PL antes del 特別控除 (収益 − 費用).
        rules: Parametros fiscales del anio.

    Returns:
        青色申告特別控除 (>= 0).
    """
    if filing_type == FilingType.SHIROIRO.value:
        return 0
    key = _AOIRO_KEY.get(filing_type, "double_entry_etax")
    full = getattr(rules.aoiro_special_deduction, key, 0)
    return max(0, min(full, business_pl))


def _materialize_journal_entries(
    session: Session,
    fiscal_year: FiscalYear,
    confirmed: list[Transaction],
    accounts: dict[str, Account],
    sales_revenue: int,
) -> None:
    """Crea los 仕訳 del 年度 desde 取引 confirmados + el 売上 editable.

    Solo regenera asientos identificados como proyecciones de este servicio.
    Si hay asientos antiguos sin origen, detiene el cálculo sin modificarlos.

    Patron de cada gasto (titular paga de su bolsillo): 借方 gasto / 貸方 事業主借.
    Patron del 売上: 借方 事業主貸 / 貸方 売上高 (cobro al titular, simplificado).

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year: 年度.
        confirmed: Transacciones confirmadas (gastos).
        accounts: Mapa de cuentas por codigo.
        sales_revenue: 売上 del 事業 (leido de `IncomeSource`, editable). Si es 0
            no se materializa el asiento de 売上.
    """
    # Nunca se supone que un asiento antiguo sin origen es descartable.
    existing = list(
        session.scalars(
            select(JournalEntry).where(
                JournalEntry.fiscal_year_id == fiscal_year.id
            )
        ).all()
    )
    if any(entry.created_by is None for entry in existing):
        raise UnidentifiedJournalEntriesError()
    for entry in existing:
        if entry.created_by == PROJECTION_CREATED_BY:
            session.delete(entry)
    session.flush()

    contra = accounts.get(ACCOUNT_OWNER_CONTRA)
    sales = accounts.get(ACCOUNT_SALES)
    drawing = accounts.get(ACCOUNT_OWNER_DRAWING)

    # 1. 売上 del 事業 (editable, leido de IncomeSource; un unico asiento anual).
    if sales is not None and drawing is not None and sales_revenue > 0:
        sales_entry = JournalEntry(
            fiscal_year_id=fiscal_year.id,
            date=date(fiscal_year.year, 12, 31),
            description="売上高（年間・事業所得）",
            created_by=PROJECTION_CREATED_BY,
        )
        sales_entry.lines = [
            JournalLine(
                side=JournalSide.DEBIT,
                account_id=drawing.id,
                amount=sales_revenue,
            ),
            JournalLine(
                side=JournalSide.CREDIT,
                account_id=sales.id,
                amount=sales_revenue,
            ),
        ]
        post_entry(session, sales_entry, commit=False)

    # 2. Gastos confirmados (gasto al 借方, 事業主借 al 貸方).
    if contra is None:
        logger.warning("Cuenta 事業主借 (312) ausente; no se materializan gastos.")
        return
    for tx in confirmed:
        allocation = transaction_allocation(tx)
        amount = allocation.business_total if allocation is not None else tx.total_amount or 0
        if amount <= 0:
            continue
        expense_account = accounts.get(tx.account_code or "599") or accounts.get("599")
        if expense_account is None:
            continue
        entry = JournalEntry(
            fiscal_year_id=fiscal_year.id,
            date=tx.date,
            description=tx.vendor or "経費",
            transaction_id=tx.id,
            created_by=PROJECTION_CREATED_BY,
        )
        rate = None
        if tx.tax_lines:
            rate = tx.tax_lines[0].get("rate")
        expense_lines = (
            [
                JournalLine(side=JournalSide.DEBIT, account_id=expense_account.id,
                            amount=line.business, tax_rate=line.original.tax_rate)
                for line in allocation.lines if line.business > 0
            ]
            if allocation is not None
            else [JournalLine(side=JournalSide.DEBIT, account_id=expense_account.id,
                              amount=amount, tax_rate=rate)]
        )
        entry.lines = [
            *expense_lines,
            JournalLine(
                side=JournalSide.CREDIT,
                account_id=contra.id,
                amount=amount,
            ),
        ]
        post_entry(session, entry, commit=False)

    session.flush()


def _build_checklist(
    confirmed_count: int,
    pending_count: int,
    deductions: list[Deduction],
    tax: TaxCalculationResult,
    prepayment: int | None,
) -> list[FilingChecklistItem]:
    """Arma la lista de prontitud del 確定申告.

    Args:
        confirmed_count: 取引 confirmados.
        pending_count: 取引 pending.
        deductions: 控除 registradas.
        tax: Resultado del calculo.

    Returns:
        Lista de `FilingChecklistItem`.
    """
    return [
        FilingChecklistItem(
            key="journal_confirmed",
            label="仕訳をすべて確認",
            done=pending_count == 0,
            detail=(
                f"確認済み {confirmed_count}件"
                if pending_count == 0
                else f"未確認 {pending_count}件 / 確認済み {confirmed_count}件"
            ),
        ),
        FilingChecklistItem(
            key="deductions_registered",
            label="控除を登録",
            done=len(deductions) > 0,
            detail=f"{len(deductions)}件の控除",
        ),
        FilingChecklistItem(
            key="prepayment_known",
            label="予定納税を確認",
            done=prepayment is not None,
            detail="未確認" if prepayment is None else "通知額を登録済み",
        ),
        FilingChecklistItem(
            key="forms_ready",
            label="申告書の内容を確認",
            done=False,
            detail=(
                "PDFは下書きです。未記入欄と提出方法を確認してください。"
                if tax.year == 2025
                else "提出用の様式は未検証です。"
            ),
        ),
    ]


def build_filing_draft(
    session: Session,
    year: int,
    *,
    rules: TaxRules | None = None,
    persist: bool = True,
    preview_projection: bool = False,
) -> FilingDraftResult:
    """Ensambla el 確定申告 completo del 年度 y persiste el `FilingDraft`.

    Args:
        session: Sesion de SQLAlchemy.
        year: 年度 (令和7 = 2025).
        rules: Parametros fiscales; si es ``None`` se cargan por `year`.
        persist: Si ``True`` materializa asientos y persiste el `FilingDraft`.

    Returns:
        `FilingDraftResult` con todos los numeros (PL, BS, calculo fiscal).

    Raises:
        ValueError: Si no existe el 年度 pedido.
        FileNotFoundError: Si no hay parametros fiscales para el anio.
    """
    if rules is None:
        rules = load_tax_rules(year)

    fiscal_year = session.scalars(
        select(FiscalYear).where(FiscalYear.year == year)
    ).first()
    if fiscal_year is None:
        raise ValueError(f"No existe el 年度 {year}.")

    locked_draft: FilingDraft | None = None
    if (
        (persist or preview_projection)
        and FiscalYearStatus(fiscal_year.status) != FiscalYearStatus.OPEN
    ):
        locked_draft = session.scalars(
            select(FilingDraft).where(FilingDraft.fiscal_year_id == fiscal_year.id)
        ).first()
        if locked_draft is None:
            raise ClosedYearWithoutDraftError()
        persist = False
        preview_projection = False

    taxpayer = fiscal_year.taxpayer
    raw_filing = fiscal_year.filing_type_override or (taxpayer.filing_type if taxpayer else None)
    # SQLite devuelve el enum como str crudo; normalizamos a su `.value`.
    filing_type = (
        getattr(raw_filing, "value", raw_filing) or FilingType.AOIRO_65.value
    )
    taxpayer_name = taxpayer.name if taxpayer else "—"

    taxpayer_profile: TaxpayerProfile | None = None
    if taxpayer is not None:
        # Una oficina ausente no se interpreta como 津島.
        office_key = getattr(taxpayer, "filing_office", None)
        taxpayer_profile = TaxpayerProfile(
            name=taxpayer.name,
            name_kana=taxpayer.name_kana,
            postal_code=taxpayer.postal_code,
            address=taxpayer.address,
            my_number_masked=_mask_my_number(taxpayer.my_number),
            birth_date_label=_era_birth_date(taxpayer.birth_date),
            occupation=taxpayer.business_type,
            filing_office_key=office_key,
        )

    # Transacciones confirmadas (las que entran al PL).
    all_txs = list(
        session.scalars(
            select(Transaction).where(Transaction.fiscal_year_id == fiscal_year.id)
        ).all()
    )
    confirmed = [
        t for t in all_txs if t.status == TransactionStatus.CONFIRMED
    ]
    pending = [t for t in all_txs if t.status == TransactionStatus.PENDING]
    confirmed_expense_total = sum(
        allocation.business_total if (allocation := transaction_allocation(t)) is not None
        else t.total_amount or 0
        for t in confirmed
    )

    # 収入 editables del 年度 (売上, 源泉, 給与…): reemplazan el hardcode previo.
    income_sources = list(
        session.scalars(
            select(IncomeSource).where(
                IncomeSource.fiscal_year_id == fiscal_year.id
            )
        ).all()
    )
    sales_revenue = jigyo_sales_revenue(income_sources)
    withholding_tax = total_withholding(income_sources)
    extra_incomes = extra_income_inputs(income_sources)

    accounts = _accounts_by_code(session)

    if persist or preview_projection:
        _materialize_journal_entries(
            session, fiscal_year, confirmed, accounts, sales_revenue
        )

    pl = income_statement(session, fiscal_year)
    bs = balance_sheet(session, fiscal_year)

    # 事業所得 = (収益 − 費用) − 青色申告特別控除.
    # 収益 = 売上 editable (asiento materializado arriba); 費用 = 経費 de los 仕訳.
    # IMPORTANTE (損益通算): si el PL es negativo (事業 en 赤字), el 事業所得 se
    # mantiene NEGATIVO — NO se acota a 0 — para que la perdida se compense contra
    # el 給与 y demas 総合課税 所得 en `compute_all_incomes`. El 青色特別控除 no puede
    # generar/aumentar perdida: `_aoiro_deduction` ya lo deja en 0 cuando el PL ≤ 0.
    business_pl = pl.net_income
    aoiro = _aoiro_deduction(filing_type, business_pl, rules)
    business_income = business_pl - aoiro

    # 控除 registradas del 年度.
    deductions = list(
        session.scalars(
            select(Deduction).where(Deduction.fiscal_year_id == fiscal_year.id)
        ).all()
    )

    # Calculo fiscal: MISMO calculate() que /tax/calculate (cuadra el 納付額).
    # 所得 = 事業所得 (del motor contable) + fuentes complementarias (給与/雑/…).
    # 源泉徴収 = Σ withholding de las IncomeSource (ya NO el ¥410k hardcodeado).
    # 税額控除 (住宅ローン控除 etc.): se restan del 所得税, no de la base imponible.
    tax_credits = total_tax_credits(deductions)
    deduction_input = deductions_to_input(deductions, year=year)
    tax_input = TaxCalculationInput(
        year=year,
        filing_type=filing_type,
        incomes=cast(
            list[IncomeInput],
            [
                {"kind": "jigyo", "amount": business_income},
                *(inc.model_dump() for inc in extra_incomes),
            ],
        ),
        deductions=deduction_input,
        withholding=WithholdingInput(
            withholding_tax=withholding_tax,
            estimated_prepayment=fiscal_year.estimated_prepayment or 0,
        ),
        tax_credits=tax_credits,
    )
    tax = calculate(tax_input, rules)

    # 住民税 (impuesto de residencia, pago futuro jun-may): reusa el 合計所得 y las
    # 控除 comunes del 所得税, con 基礎/扶養 propios del 住民税. Los 扶養親族 son los
    # mismos que entraron al 所得税 (deduction_input.dependents).
    resident_tax = calculate_resident_tax(tax, deduction_input.dependents, rules)

    checklist = _build_checklist(
        len(confirmed), len(pending), deductions, tax, fiscal_year.estimated_prepayment
    )

    # Persistir el FilingDraft (snapshot de los numeros).
    draft = _persist_draft(
        session,
        fiscal_year=fiscal_year,
        tax=tax,
        pl=pl,
        bs=bs,
        aoiro=aoiro,
        business_income=business_income,
        persist=persist,
    )
    if locked_draft is not None:
        draft = locked_draft

    return FilingDraftResult(
        draft_id=draft.id,
        year=year,
        filing_type=filing_type,
        taxpayer_name=taxpayer_name,
        income_statement=pl,
        balance_sheet=bs,
        aoiro_deduction=aoiro,
        business_income=business_income,
        sales_revenue=sales_revenue,
        salary_revenue=sum(item.revenue for item in extra_incomes if item.kind == "kyuyo"),
        confirmed_count=len(confirmed),
        pending_count=len(pending),
        confirmed_expense_total=confirmed_expense_total,
        tax=tax,
        resident_tax=resident_tax,
        taxpayer_profile=taxpayer_profile,
        deductions=deductions,
        checklist=checklist,
    )


def _persist_draft(
    session: Session,
    *,
    fiscal_year: FiscalYear,
    tax: TaxCalculationResult,
    pl: IncomeStatement,
    bs: BalanceSheet,
    aoiro: int,
    business_income: int,
    persist: bool,
) -> FilingDraft | FilingDraftStub:
    """Crea o actualiza el `FilingDraft` del 年度 con el snapshot calculado.

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year: 年度.
        tax: Resultado del calculo.
        pl: 損益計算書.
        bs: 貸借対照表.
        aoiro: 青色申告特別控除.
        business_income: 事業所得.
        persist: Si ``False`` devuelve un stub con id sin tocar la BD.

    Returns:
        El `FilingDraft` persistido (o un stub con id efimero si ``persist`` es
        ``False``).
    """
    computed = {
        "business_income": business_income,
        "aoiro_deduction": aoiro,
        "pl_net_income": pl.net_income,
        "bs_is_balanced": bs.is_balanced,
        "taxable_income": tax.taxable_income,
        "total_tax": tax.total_tax,
        "final_amount": tax.final_amount,
    }

    if not persist:
        return FilingDraftStub(id=uuid.uuid4())

    draft = session.scalars(
        select(FilingDraft).where(
            FilingDraft.fiscal_year_id == fiscal_year.id
        )
    ).first()
    if draft is None:
        draft = FilingDraft(fiscal_year_id=fiscal_year.id, computed=computed)
        session.add(draft)
    else:
        draft.computed = cast(dict[str, object], computed)
    session.commit()
    session.refresh(draft)
    return draft


@dataclass
class FilingDraftStub:
    """Stub de `FilingDraft` con id efimero (modo no-persistente, para tests)."""

    id: uuid.UUID


def collect_ledgers(
    session: Session, fiscal_year: FiscalYear
) -> list[Ledger]:
    """Construye el 総勘定元帳 de todas las cuentas con movimientos del 年度.

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year: 年度.

    Returns:
        Lista de `Ledger` (una por cuenta con movimientos), ordenada por codigo.
    """
    tb: TrialBalance = trial_balance(session, fiscal_year)
    accounts = _accounts_by_code(session)
    ledgers: list[Ledger] = []
    for row in tb.rows:
        account = accounts.get(row.account_code)
        if account is None:
            continue
        ledgers.append(build_ledger(session, account, fiscal_year))
    return ledgers
