"""Tests del motor 複式簿記 (plan 03 §2).

Escenario conocido (個人事業主, montos en yenes):

  Apertura:   現金 1,000,000      / 元入金 1,000,000
  Venta:      現金   500,000      / 売上高   500,000
  Gasto viaje: 旅費交通費 30,000   / 現金      30,000
  Gasto comms: 通信費      20,000   / 現金      20,000

Resultados esperados:
  PL:  収益 500,000 − 費用 50,000 = 所得 450,000
  BS:  資産(現金) = 1,000,000 + 500,000 − 30,000 − 20,000 = 1,450,000
       資本(元入金) = 1,000,000 ; 負債 = 0 ; 所得(PL) = 450,000
       => 1,450,000 = 0 + 1,000,000 + 450,000  (cuadra)
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.accounting import (
    UnbalancedEntryError,
    balance_sheet,
    build_ledger,
    income_statement,
    post_entry,
    trial_balance,
)
from app.models import Account, FiscalYear, JournalEntry, JournalLine, Taxpayer
from app.models.enums import FilingType, FiscalYearStatus, JournalSide
from app.seed.accounts import seed_accounts


@pytest.fixture
def fiscal_year(session: Session) -> FiscalYear:
    """Taxpayer + FiscalYear + cuentas semilla listos para asentar."""
    tp = Taxpayer(name="テスト事業主", filing_type=FilingType.AOIRO_65)
    session.add(tp)
    session.commit()
    fy = FiscalYear(
        taxpayer_id=tp.id,
        year=2025,
        rules_ref="tax_rules/2025.json",
        status=FiscalYearStatus.OPEN,
    )
    session.add(fy)
    session.commit()
    seed_accounts(session)
    return fy


def _acc(session: Session, code: str) -> Account:
    """Devuelve la cuenta semilla por codigo."""
    acc = session.scalar(select(Account).where(Account.code == code))
    assert acc is not None, f"cuenta {code} no encontrada"
    return acc


def _entry(
    session: Session,
    fy: FiscalYear,
    when: date,
    desc: str,
    debit: tuple[str, int],
    credit: tuple[str, int],
) -> JournalEntry:
    """Construye un asiento simple de 2 lineas (1 debito, 1 credito)."""
    return JournalEntry(
        fiscal_year_id=fy.id,
        date=when,
        description=desc,
        lines=[
            JournalLine(
                side=JournalSide.DEBIT, account_id=_acc(session, debit[0]).id, amount=debit[1]
            ),
            JournalLine(
                side=JournalSide.CREDIT, account_id=_acc(session, credit[0]).id, amount=credit[1]
            ),
        ],
    )


def _post_scenario(session: Session, fy: FiscalYear) -> None:
    """Asienta el escenario conocido del modulo."""
    post_entry(
        session,
        _entry(session, fy, date(2025, 1, 1), "開業 元入", ("101", 1_000_000), ("301", 1_000_000)),
    )
    post_entry(
        session,
        _entry(session, fy, date(2025, 3, 1), "現金売上", ("101", 500_000), ("401", 500_000)),
    )
    post_entry(
        session,
        _entry(session, fy, date(2025, 4, 1), "電車代", ("501", 30_000), ("101", 30_000)),
    )
    post_entry(
        session,
        _entry(session, fy, date(2025, 5, 1), "携帯料金", ("505", 20_000), ("101", 20_000)),
    )


def test_post_entry_rejects_unbalanced(session: Session, fiscal_year: FiscalYear) -> None:
    """Un asiento con Σ借方 != Σ貸方 es rechazado y no se persiste."""
    bad = _entry(
        session, fiscal_year, date(2025, 2, 1), "desbalanceado", ("101", 1000), ("401", 999)
    )
    with pytest.raises(UnbalancedEntryError):
        post_entry(session, bad)

    session.rollback()
    # No quedo ningun asiento persistido.
    assert session.scalar(select(JournalEntry).limit(1)) is None


def test_post_entry_accepts_balanced(session: Session, fiscal_year: FiscalYear) -> None:
    """Un asiento balanceado se persiste con id."""
    entry = _entry(
        session, fiscal_year, date(2025, 2, 1), "ok", ("101", 1000), ("401", 1000)
    )
    posted = post_entry(session, entry)
    assert posted.id is not None
    assert session.scalar(select(JournalEntry).limit(1)) is not None


def test_build_ledger_cash_account(session: Session, fiscal_year: FiscalYear) -> None:
    """総勘定元帳 del 現金: 4 movimientos y saldo final 1,450,000."""
    _post_scenario(session, fiscal_year)
    cash = _acc(session, "101")
    ledger = build_ledger(session, cash, fiscal_year)

    assert len(ledger.movements) == 4
    assert ledger.total_debit == 1_500_000  # 1,000,000 + 500,000
    assert ledger.total_credit == 50_000  # 30,000 + 20,000
    assert ledger.balance == 1_450_000
    # El saldo acumulado del ultimo movimiento coincide con el balance.
    assert ledger.movements[-1].balance == 1_450_000


def test_trial_balance_balanced(session: Session, fiscal_year: FiscalYear) -> None:
    """試算表: Σ debitos = Σ creditos globales."""
    _post_scenario(session, fiscal_year)
    tb = trial_balance(session, fiscal_year)

    assert tb.is_balanced is True
    assert tb.total_debit == tb.total_credit
    # Σ debitos = 1,000,000 + 500,000 + 30,000 + 20,000 = 1,550,000
    assert tb.total_debit == 1_550_000


def test_income_statement_known_numbers(session: Session, fiscal_year: FiscalYear) -> None:
    """損益計算書: 収益 500,000 − 費用 50,000 = 所得 450,000."""
    _post_scenario(session, fiscal_year)
    pl = income_statement(session, fiscal_year)

    assert pl.total_revenue == 500_000
    assert pl.total_expense == 50_000
    assert pl.net_income == 450_000


def test_balance_sheet_known_numbers_and_validation(
    session: Session, fiscal_year: FiscalYear
) -> None:
    """貸借対照表: 資産 = 負債 + 資本 + 所得, y 所得 BS = 所得 PL."""
    _post_scenario(session, fiscal_year)
    bs = balance_sheet(session, fiscal_year)
    pl = income_statement(session, fiscal_year)

    assert bs.total_assets == 1_450_000
    assert bs.total_liabilities == 0
    assert bs.total_equity == 1_000_000  # 元入金
    assert bs.net_income == 450_000
    # Validacion contable: 所得 del BS == 所得 del PL.
    assert bs.net_income == pl.net_income
    # 資産 = 負債 + 資本 + 所得.
    assert bs.is_balanced is True
    assert bs.total_assets == bs.total_liabilities + bs.total_equity + bs.net_income


def test_multi_line_entry_balances(session: Session, fiscal_year: FiscalYear) -> None:
    """Un asiento de 3 lineas (1 debito, 2 creditos) que cuadra se acepta."""
    entry = JournalEntry(
        fiscal_year_id=fiscal_year.id,
        date=date(2025, 6, 1),
        description="複合仕訳",
        lines=[
            JournalLine(side=JournalSide.DEBIT, account_id=_acc(session, "101").id, amount=10_000),
            JournalLine(side=JournalSide.CREDIT, account_id=_acc(session, "401").id, amount=7_000),
            JournalLine(side=JournalSide.CREDIT, account_id=_acc(session, "409").id, amount=3_000),
        ],
    )
    posted = post_entry(session, entry)
    assert posted.id is not None
