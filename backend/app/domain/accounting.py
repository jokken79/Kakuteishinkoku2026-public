"""Motor de contabilidad por partida doble (複式簿記) — plan 03 §2.

Funciones puras y testables sobre el modelo de datos. Reglas:

- Invariante de asiento (仕訳): Σ借方 = Σ貸方. `post_entry` lo valida y rechaza
  asientos desbalanceados con `UnbalancedEntryError`.
- Derivaciones (calculadas, no almacenadas):
  - `build_ledger`  -> 総勘定元帳 (movimientos + saldo de una cuenta).
  - `trial_balance` -> 試算表 (debitos/creditos por cuenta).
  - `income_statement` -> 損益計算書 (収益 - 費用 = 所得金額).
  - `balance_sheet` -> 貸借対照表 (資産 = 負債 + 資本); valida que el 所得 del
    PL coincida con el del BR.

Todos los montos son enteros (yenes). El saldo de una cuenta se calcula segun
su "lado natural": activos y gastos aumentan por 借方; pasivos, capital e
ingresos aumentan por 貸方.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Account,
    FiscalYear,
    JournalEntry,
    JournalLine,
)
from app.models.enums import AccountCategory, JournalSide


class UnbalancedEntryError(ValueError):
    """Se lanza cuando un 仕訳 no cumple Σ借方 = Σ貸方."""


# Categorias cuyo saldo aumenta por el 借方 (debit-normal).
_DEBIT_NORMAL: frozenset[AccountCategory] = frozenset(
    {AccountCategory.ASSET, AccountCategory.EXPENSE}
)


def _entry_totals(lines: list[JournalLine]) -> tuple[int, int]:
    """Suma debitos y creditos de una lista de lineas.

    Args:
        lines: Lineas del asiento.

    Returns:
        Tupla ``(total_debit, total_credit)``.
    """
    debit = sum(line.amount for line in lines if line.side == JournalSide.DEBIT)
    credit = sum(line.amount for line in lines if line.side == JournalSide.CREDIT)
    return debit, credit


def validate_entry(entry: JournalEntry) -> None:
    """Valida la invariante Σ借方 = Σ貸方 de un asiento.

    Args:
        entry: Asiento a validar (debe tener `lines` cargadas).

    Raises:
        UnbalancedEntryError: Si el asiento no tiene lineas o no balancea.
    """
    if not entry.lines:
        raise UnbalancedEntryError("El asiento no tiene lineas (仕訳明細 vacio)")
    debit, credit = _entry_totals(entry.lines)
    if debit != credit:
        raise UnbalancedEntryError(
            f"Asiento desbalanceado: 借方={debit} != 貸方={credit}"
        )


def post_entry(session: Session, entry: JournalEntry, *, commit: bool = True) -> JournalEntry:
    """Valida y persiste un asiento (仕訳).

    Rechaza el asiento si Σ借方 != Σ貸方 (no escribe nada en ese caso).

    Args:
        session: Sesion de SQLAlchemy.
        entry: Asiento a registrar (con sus `lines`).
        commit: Si ``True`` confirma la transaccion.

    Returns:
        El asiento persistido (con id asignado).

    Raises:
        UnbalancedEntryError: Si el asiento no balancea.
    """
    validate_entry(entry)
    session.add(entry)
    session.flush()
    if commit:
        session.commit()
    return entry


@dataclass
class LedgerMovement:
    """Movimiento de una cuenta en el 総勘定元帳.

    Args:
        entry_id: Id del asiento de origen.
        date_iso: Fecha del asiento (ISO ``YYYY-MM-DD``).
        description:摘要 del asiento.
        debit: Monto al 借方 (0 si la linea es credito).
        credit: Monto al 貸方 (0 si la linea es debito).
        balance: Saldo acumulado tras el movimiento (segun lado natural).
    """

    entry_id: uuid.UUID
    date_iso: str
    description: str | None
    debit: int
    credit: int
    balance: int


@dataclass
class Ledger:
    """総勘定元帳 de una cuenta.

    Args:
        account_id: Id de la cuenta.
        account_code: Codigo de la cuenta.
        account_name: Nombre de la cuenta.
        category: Categoria contable.
        movements: Movimientos en orden cronologico.
        total_debit: Suma de debitos.
        total_credit: Suma de creditos.
        balance: Saldo final (segun lado natural de la categoria).
    """

    account_id: uuid.UUID
    account_code: str
    account_name: str
    category: AccountCategory
    movements: list[LedgerMovement] = field(default_factory=list)
    total_debit: int = 0
    total_credit: int = 0
    balance: int = 0


def _natural_balance(category: AccountCategory, debit: int, credit: int) -> int:
    """Calcula el saldo segun el lado natural de la categoria.

    Args:
        category: Categoria de la cuenta.
        debit: Total debitos.
        credit: Total creditos.

    Returns:
        ``debit - credit`` para cuentas debit-normal, ``credit - debit`` para el
        resto.
    """
    if category in _DEBIT_NORMAL:
        return debit - credit
    return credit - debit


def _lines_for_year(session: Session, fiscal_year_id: uuid.UUID) -> list[JournalLine]:
    """Devuelve las lineas de asiento del 年度, con cuenta y asiento cargados.

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year_id: Id del 年度.

    Returns:
        Lista de `JournalLine` del ejercicio.
    """
    stmt = (
        select(JournalLine)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .where(JournalEntry.fiscal_year_id == fiscal_year_id)
    )
    return list(session.scalars(stmt).all())


def build_ledger(session: Session, account: Account, fiscal_year: FiscalYear) -> Ledger:
    """Construye el 総勘定元帳 de una cuenta para un ejercicio.

    Args:
        session: Sesion de SQLAlchemy.
        account: Cuenta a reagrupar.
        fiscal_year: Ejercicio fiscal.

    Returns:
        `Ledger` con movimientos en orden cronologico y saldo acumulado.
    """
    stmt = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .where(
            JournalEntry.fiscal_year_id == fiscal_year.id,
            JournalLine.account_id == account.id,
        )
        .order_by(JournalEntry.date, JournalEntry.id)
    )
    rows = session.execute(stmt).all()

    ledger = Ledger(
        account_id=account.id,
        account_code=account.code,
        account_name=account.name,
        category=account.category,
    )
    running = 0
    for line, entry in rows:
        debit = line.amount if line.side == JournalSide.DEBIT else 0
        credit = line.amount if line.side == JournalSide.CREDIT else 0
        ledger.total_debit += debit
        ledger.total_credit += credit
        running = _natural_balance(ledger.category, ledger.total_debit, ledger.total_credit)
        ledger.movements.append(
            LedgerMovement(
                entry_id=entry.id,
                date_iso=entry.date.isoformat(),
                description=entry.description,
                debit=debit,
                credit=credit,
                balance=running,
            )
        )
    ledger.balance = _natural_balance(
        ledger.category, ledger.total_debit, ledger.total_credit
    )
    return ledger


@dataclass
class TrialBalanceRow:
    """Fila del 試算表.

    Args:
        account_id: Id de la cuenta.
        account_code: Codigo.
        account_name: Nombre.
        category: Categoria contable.
        debit: Total debitos.
        credit: Total creditos.
        balance: Saldo segun lado natural.
    """

    account_id: uuid.UUID
    account_code: str
    account_name: str
    category: AccountCategory
    debit: int
    credit: int
    balance: int


@dataclass
class TrialBalance:
    """試算表 del ejercicio.

    Args:
        rows: Filas por cuenta (ordenadas por codigo).
        total_debit: Suma global de debitos.
        total_credit: Suma global de creditos.
        is_balanced: ``True`` si total_debit == total_credit.
    """

    rows: list[TrialBalanceRow] = field(default_factory=list)
    total_debit: int = 0
    total_credit: int = 0
    is_balanced: bool = True


def trial_balance(session: Session, fiscal_year: FiscalYear) -> TrialBalance:
    """Calcula el 試算表 (debitos/creditos por cuenta) del ejercicio.

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year: Ejercicio fiscal.

    Returns:
        `TrialBalance` con una fila por cuenta con movimientos y totales.
    """
    lines = _lines_for_year(session, fiscal_year.id)

    # Acumular por account_id.
    debit_by_acc: dict[uuid.UUID, int] = {}
    credit_by_acc: dict[uuid.UUID, int] = {}
    for line in lines:
        if line.side == JournalSide.DEBIT:
            debit_by_acc[line.account_id] = debit_by_acc.get(line.account_id, 0) + line.amount
        else:
            credit_by_acc[line.account_id] = (
                credit_by_acc.get(line.account_id, 0) + line.amount
            )

    account_ids = set(debit_by_acc) | set(credit_by_acc)
    accounts = {
        acc.id: acc
        for acc in session.scalars(
            select(Account).where(Account.id.in_(account_ids))
        ).all()
    }

    tb = TrialBalance()
    for acc_id in account_ids:
        acc = accounts[acc_id]
        debit = debit_by_acc.get(acc_id, 0)
        credit = credit_by_acc.get(acc_id, 0)
        tb.rows.append(
            TrialBalanceRow(
                account_id=acc_id,
                account_code=acc.code,
                account_name=acc.name,
                category=acc.category,
                debit=debit,
                credit=credit,
                balance=_natural_balance(acc.category, debit, credit),
            )
        )
        tb.total_debit += debit
        tb.total_credit += credit

    tb.rows.sort(key=lambda r: r.account_code)
    tb.is_balanced = tb.total_debit == tb.total_credit
    return tb


@dataclass
class IncomeStatementLine:
    """Linea del 損益計算書.

    Args:
        account_code: Codigo de la cuenta.
        account_name: Nombre.
        amount: Importe (saldo natural de la cuenta).
    """

    account_code: str
    account_name: str
    amount: int


@dataclass
class IncomeStatement:
    """損益計算書 (PL).

    Args:
        revenues: Lineas de 収益.
        expenses: Lineas de 費用.
        total_revenue: Σ収益.
        total_expense: Σ費用.
        net_income: 所得金額 (収益 - 費用), antes de 青色特別控除.
    """

    revenues: list[IncomeStatementLine] = field(default_factory=list)
    expenses: list[IncomeStatementLine] = field(default_factory=list)
    total_revenue: int = 0
    total_expense: int = 0
    net_income: int = 0


def income_statement(session: Session, fiscal_year: FiscalYear) -> IncomeStatement:
    """Calcula el 損益計算書: 収益 - 費用 = 所得金額.

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year: Ejercicio fiscal.

    Returns:
        `IncomeStatement` con lineas de ingresos/gastos y el resultado neto.
    """
    tb = trial_balance(session, fiscal_year)
    pl = IncomeStatement()

    for row in tb.rows:
        if row.category == AccountCategory.REVENUE:
            pl.revenues.append(
                IncomeStatementLine(row.account_code, row.account_name, row.balance)
            )
            pl.total_revenue += row.balance
        elif row.category == AccountCategory.EXPENSE:
            pl.expenses.append(
                IncomeStatementLine(row.account_code, row.account_name, row.balance)
            )
            pl.total_expense += row.balance

    pl.net_income = pl.total_revenue - pl.total_expense
    return pl


@dataclass
class BalanceSheetLine:
    """Linea del 貸借対照表.

    Args:
        account_code: Codigo de la cuenta.
        account_name: Nombre.
        amount: Saldo natural de la cuenta.
    """

    account_code: str
    account_name: str
    amount: int


@dataclass
class BalanceSheet:
    """貸借対照表 (BS).

    Args:
        assets: Lineas de 資産.
        liabilities: Lineas de 負債.
        equity: Lineas de 資本.
        total_assets: Σ資産.
        total_liabilities: Σ負債.
        total_equity: Σ資本 (元入金/事業主貸借, sin el resultado del ejercicio).
        net_income: 所得 del ejercicio (= net_income del PL), parte del capital.
        is_balanced: ``True`` si 資産 = 負債 + 資本 + 所得.
    """

    assets: list[BalanceSheetLine] = field(default_factory=list)
    liabilities: list[BalanceSheetLine] = field(default_factory=list)
    equity: list[BalanceSheetLine] = field(default_factory=list)
    total_assets: int = 0
    total_liabilities: int = 0
    total_equity: int = 0
    net_income: int = 0
    is_balanced: bool = False


def balance_sheet(session: Session, fiscal_year: FiscalYear) -> BalanceSheet:
    """Calcula el 貸借対照表 y valida 資産 = 負債 + 資本 (+ 所得).

    El resultado del ejercicio (所得 del PL) forma parte del patrimonio: por eso
    la igualdad contable se cumple como ``資産 = 負債 + 資本 + 所得``. Esto valida
    indirectamente que el 所得 del PL coincide con el del BS (partida doble).

    Args:
        session: Sesion de SQLAlchemy.
        fiscal_year: Ejercicio fiscal.

    Returns:
        `BalanceSheet` con secciones de activo/pasivo/capital y validacion.
    """
    tb = trial_balance(session, fiscal_year)
    pl = income_statement(session, fiscal_year)
    bs = BalanceSheet(net_income=pl.net_income)

    for row in tb.rows:
        if row.category == AccountCategory.ASSET:
            bs.assets.append(BalanceSheetLine(row.account_code, row.account_name, row.balance))
            bs.total_assets += row.balance
        elif row.category == AccountCategory.LIABILITY:
            bs.liabilities.append(
                BalanceSheetLine(row.account_code, row.account_name, row.balance)
            )
            bs.total_liabilities += row.balance
        elif row.category == AccountCategory.EQUITY:
            bs.equity.append(
                BalanceSheetLine(row.account_code, row.account_name, row.balance)
            )
            bs.total_equity += row.balance

    bs.is_balanced = (
        bs.total_assets == bs.total_liabilities + bs.total_equity + bs.net_income
    )
    return bs
