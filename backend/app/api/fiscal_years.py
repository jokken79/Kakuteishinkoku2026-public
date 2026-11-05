"""Router del ciclo multi-año fiscal (年度).

Endpoints (bajo `/api/v1`):

- ``GET   /fiscal-years``         — lista los 年度 del contribuyente (year +
  status), ordenados desc.
- ``POST  /fiscal-years``         — crea un 年度 nuevo (idempotente: si ya existe
  para ese año, lo devuelve). Reúsa `ensure_fiscal_year` del service.
- ``PATCH /fiscal-years/{year}``  — cambia el status del 年度 (open/closed/filed).

Permite que la app funcione año tras año (2025, 2026, 2027...) sin tocar código:
el selector de 年度 del frontend consume estos endpoints para listar y abrir años.

Diseño single-user (MVP): hay un único `Taxpayer`; si aún no existe, ``POST`` lo
crea junto al primer 年度.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.fiscal_year_guard import require_open_fiscal_year
from app.db.session import get_db
from app.domain.accounting import post_entry
from app.models.entities import (
    Account,
    FiscalYear,
    JournalEntry,
    JournalLine,
    OpeningBalance,
    Taxpayer,
)
from app.models.enums import AccountCategory, FilingType, FiscalYearStatus, JournalSide
from app.services.fiscal_years import (
    ensure_fiscal_year,
    get_taxpayer,
    list_fiscal_years,
    set_fiscal_year_status,
)
from app.services.tax_rules import load_tax_rules

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fiscal-years"])

OPENING_BALANCE_CREATED_BY = "opening_balance"
OPENING_BALANCE_DESCRIPTION = "期首残高"
OPENING_BALANCE_MAX_AMOUNT = 100_000_000
OPENING_BALANCE_CATEGORIES = frozenset(
    {AccountCategory.ASSET, AccountCategory.LIABILITY, AccountCategory.EQUITY}
)


# --- Schemas --------------------------------------------------------------


class FiscalYearOut(BaseModel):
    """Un 年度 del contribuyente.

    Args:
        year: Año fiscal (西暦, ej. 2025).
        status: Estado del ciclo (open/closed/filed).
    """

    year: int
    status: FiscalYearStatus
    rules_available: bool


class FiscalYearList(BaseModel):
    """Respuesta de `GET /fiscal-years`.

    Args:
        years: 年度 del contribuyente (más reciente primero).
        active_year: Año OPEN más reciente (default del selector), o ``None``.
    """

    years: list[FiscalYearOut]
    active_year: int | None


class FiscalYearCreate(BaseModel):
    """Cuerpo de `POST /fiscal-years`.

    Args:
        year: Año fiscal a abrir (西暦). Rango razonable para evitar typos.
    """

    year: int = Field(ge=2000, le=2100)


class FiscalYearStatusPatch(BaseModel):
    """Cuerpo de `PATCH /fiscal-years/{year}`.

    Args:
        status: Nuevo estado del ciclo (open/closed/filed).
    """

    status: FiscalYearStatus


class EstimatedPrepayment(BaseModel):
    """Importe notificado; null indica que todavía no se ha informado."""

    amount: int | None = Field(default=None, ge=0, le=999_999_999, strict=True)


class FilingTypeByYearOut(BaseModel):
    """Distingue confirmación anual del dato heredado del perfil."""

    value: FilingType
    source: Literal["year", "profile_unconfirmed"]


class FilingTypeByYearIn(BaseModel):
    value: FilingType
    backup_confirmed: Literal[True]


def _prepayment_year(db: Session, year: int) -> FiscalYear:
    fiscal_year = db.scalars(select(FiscalYear).where(FiscalYear.year == year)).first()
    if fiscal_year is None:
        raise HTTPException(status_code=404, detail="年度が見つかりません。")
    return fiscal_year


def _filing_type_out(fiscal_year: FiscalYear) -> FilingTypeByYearOut:
    explicit = fiscal_year.filing_type_override
    value = explicit or fiscal_year.taxpayer.filing_type
    return FilingTypeByYearOut(
        value=FilingType(value), source="year" if explicit else "profile_unconfirmed"
    )


@router.get("/fiscal-years/{year}/filing-type", response_model=FilingTypeByYearOut)
def get_filing_type_by_year(
    year: int, response: Response, db: Session = Depends(get_db),
) -> FilingTypeByYearOut:
    response.headers["Cache-Control"] = "no-store"
    return _filing_type_out(_prepayment_year(db, year))


@router.put("/fiscal-years/{year}/filing-type", response_model=FilingTypeByYearOut)
def put_filing_type_by_year(
    year: int, payload: FilingTypeByYearIn, db: Session = Depends(get_db),
) -> FilingTypeByYearOut:
    fiscal_year = _prepayment_year(db, year)
    require_open_fiscal_year(fiscal_year)
    fiscal_year.filing_type_override = payload.value
    db.commit()
    return _filing_type_out(fiscal_year)


@router.get("/fiscal-years/{year}/estimated-prepayment", response_model=EstimatedPrepayment)
def get_estimated_prepayment(
    year: int, response: Response, db: Session = Depends(get_db),
) -> EstimatedPrepayment:
    response.headers["Cache-Control"] = "no-store"
    return EstimatedPrepayment(amount=_prepayment_year(db, year).estimated_prepayment)


@router.put("/fiscal-years/{year}/estimated-prepayment", response_model=EstimatedPrepayment)
def put_estimated_prepayment(
    year: int, payload: EstimatedPrepayment, db: Session = Depends(get_db),
) -> EstimatedPrepayment:
    fiscal_year = _prepayment_year(db, year)
    require_open_fiscal_year(fiscal_year)
    fiscal_year.estimated_prepayment = payload.amount
    db.commit()
    return EstimatedPrepayment(amount=fiscal_year.estimated_prepayment)


class OpeningBalanceLineIn(BaseModel):
    """Una línea de saldo inicial enviada desde la UI."""

    account_code: str = Field(min_length=1, max_length=32)
    amount: int = Field(ge=0, le=OPENING_BALANCE_MAX_AMOUNT)


class OpeningBalanceUpsert(BaseModel):
    """Cuerpo de `POST /fiscal-years/{year}/opening-balances`."""

    balances: list[OpeningBalanceLineIn] = Field(default_factory=list, max_length=20)


class OpeningBalanceLineOut(BaseModel):
    """Una línea persistida de 期首残高."""

    account_code: str
    account_name: str
    category: AccountCategory
    amount: int


class OpeningBalanceSummary(BaseModel):
    """Resumen contable de los saldos de apertura de un 年度."""

    year: int
    balances: list[OpeningBalanceLineOut]
    total_assets: int
    total_liabilities: int
    total_equity: int
    imbalance: int
    is_balanced: bool
    journal_entry_id: UUID | None


# --- Helpers --------------------------------------------------------------


def _rules_available(year: int) -> bool:
    """Devuelve si existen parámetros fiscales para el año."""
    try:
        load_tax_rules(year)
    except FileNotFoundError:
        return False
    return True


def _active_year(years: list[FiscalYearOut]) -> int | None:
    """Devuelve el año activo evitando años sin tax_rules cuando sea posible.

    Args:
        years: 年度 ya ordenados por año descendente.

    Returns:
        El año OPEN más reciente con parámetros fiscales, o el más reciente con
        parámetros, o el más reciente absoluto si no hay reglas en ninguno.
    """
    for fy in years:
        if fy.status == FiscalYearStatus.OPEN and fy.rules_available:
            return fy.year
    for fy in years:
        if fy.rules_available:
            return fy.year
    return years[0].year if years else None


def _fiscal_year_out(fy: FiscalYear) -> FiscalYearOut:
    """Serializa un `FiscalYear` con disponibilidad de reglas fiscales."""
    return FiscalYearOut(
        year=fy.year,
        status=FiscalYearStatus(fy.status),
        rules_available=_rules_available(fy.year),
    )


def _resolve_year(db: Session, year: int) -> FiscalYear:
    """Resuelve el 年度 del taxpayer single-user o lanza 404."""
    taxpayer = get_taxpayer(db)
    if taxpayer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "no_taxpayer",
                "message": "納税者が登録されていません。",
                "details": {},
            },
        )
    fy = db.scalars(
        select(FiscalYear).where(
            FiscalYear.taxpayer_id == taxpayer.id, FiscalYear.year == year
        )
    ).first()
    if fy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "no_fiscal_year",
                "message": f"{year}年度が見つかりませんでした。",
                "details": {"year": year},
            },
        )
    return fy


def _accounts_by_code(db: Session, codes: set[str]) -> dict[str, Account]:
    """Carga cuentas contables por código y valida que sean de balance sheet."""
    if not codes:
        return {}
    accounts = {
        account.code: account
        for account in db.scalars(select(Account).where(Account.code.in_(codes))).all()
    }
    missing = sorted(codes - set(accounts))
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unknown_account_code",
                "message": "存在しない勘定科目があります。",
                "details": {"account_codes": missing},
            },
        )
    invalid = sorted(
        code
        for code, account in accounts.items()
        if AccountCategory(account.category) not in OPENING_BALANCE_CATEGORIES
    )
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_opening_account",
                "message": "期首残高には資産・負債・資本の勘定科目だけ使えます。",
                "details": {"account_codes": invalid},
            },
        )
    return accounts


def _totals(
    lines: list[OpeningBalanceLineIn], accounts: dict[str, Account]
) -> tuple[int, int, int]:
    """Calcula totales de activo, pasivo y capital para validar apertura."""
    total_assets = 0
    total_liabilities = 0
    total_equity = 0
    for line in lines:
        category = AccountCategory(accounts[line.account_code].category)
        if category == AccountCategory.ASSET:
            total_assets += line.amount
        elif category == AccountCategory.LIABILITY:
            total_liabilities += line.amount
        elif category == AccountCategory.EQUITY:
            total_equity += line.amount
    return total_assets, total_liabilities, total_equity


def _opening_journal_entry_id(db: Session, fy: FiscalYear) -> UUID | None:
    """Devuelve el 仕訳 generado para 期首残高, si existe."""
    return db.scalars(
        select(JournalEntry.id).where(
            JournalEntry.fiscal_year_id == fy.id,
            JournalEntry.created_by == OPENING_BALANCE_CREATED_BY,
        )
    ).first()


def _opening_summary(db: Session, fy: FiscalYear) -> OpeningBalanceSummary:
    """Construye la respuesta pública de saldos de apertura."""
    rows = (
        db.execute(
            select(OpeningBalance, Account)
            .join(Account, OpeningBalance.account_id == Account.id)
            .where(OpeningBalance.fiscal_year_id == fy.id)
            .order_by(Account.code)
        )
        .all()
    )
    balances = [
        OpeningBalanceLineOut(
            account_code=account.code,
            account_name=account.name,
            category=AccountCategory(account.category),
            amount=opening.amount,
        )
        for opening, account in rows
    ]
    total_assets = sum(
        line.amount for line in balances if line.category == AccountCategory.ASSET
    )
    total_liabilities = sum(
        line.amount for line in balances if line.category == AccountCategory.LIABILITY
    )
    total_equity = sum(
        line.amount for line in balances if line.category == AccountCategory.EQUITY
    )
    imbalance = total_assets - total_liabilities - total_equity
    return OpeningBalanceSummary(
        year=fy.year,
        balances=balances,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        imbalance=imbalance,
        is_balanced=imbalance == 0,
        journal_entry_id=_opening_journal_entry_id(db, fy),
    )


def _delete_existing_opening_balance(db: Session, fy: FiscalYear) -> None:
    """Borra saldos y 仕訳 de apertura existentes para reemplazo idempotente."""
    for row in db.scalars(
        select(OpeningBalance).where(OpeningBalance.fiscal_year_id == fy.id)
    ).all():
        db.delete(row)
    for entry in db.scalars(
        select(JournalEntry).where(
            JournalEntry.fiscal_year_id == fy.id,
            JournalEntry.created_by == OPENING_BALANCE_CREATED_BY,
        )
    ).all():
        db.delete(entry)


# --- Endpoints ------------------------------------------------------------


@router.get("/fiscal-years", response_model=FiscalYearList)
def get_fiscal_years(db: Session = Depends(get_db)) -> FiscalYearList:
    """Lista los 年度 del contribuyente (year + status), ordenados desc.

    Args:
        db: Sesión de BD.

    Returns:
        `FiscalYearList` con los años y el año activo por defecto (OPEN más
        reciente). Sin `Taxpayer` aún => lista vacía, ``active_year=None``.
    """
    taxpayer = get_taxpayer(db)
    if taxpayer is None:
        return FiscalYearList(years=[], active_year=None)
    years = [_fiscal_year_out(fy) for fy in list_fiscal_years(db, taxpayer)]
    return FiscalYearList(years=years, active_year=_active_year(years))


@router.post(
    "/fiscal-years",
    response_model=FiscalYearOut,
    status_code=status.HTTP_200_OK,
)
def create_fiscal_year(
    payload: FiscalYearCreate, db: Session = Depends(get_db)
) -> FiscalYearOut:
    """Crea un 年度 nuevo (idempotente: si ya existe lo devuelve).

    Si aún no hay `Taxpayer`, lo crea junto al primer 年度 (single-user MVP).

    Args:
        payload: Año a abrir.
        db: Sesión de BD.

    Returns:
        `FiscalYearOut` del 年度 creado o ya existente.
    """
    taxpayer = get_taxpayer(db)
    if taxpayer is None:
        taxpayer = Taxpayer(name="—")
        db.add(taxpayer)
        db.flush()
    fy = ensure_fiscal_year(db, taxpayer, payload.year)
    db.commit()
    db.refresh(fy)
    return _fiscal_year_out(fy)


@router.patch("/fiscal-years/{year}", response_model=FiscalYearOut)
def patch_fiscal_year(
    year: int, payload: FiscalYearStatusPatch, db: Session = Depends(get_db)
) -> FiscalYearOut:
    """Cambia el status de un 年度 existente (open/closed/filed).

    Args:
        year: Año fiscal a modificar.
        payload: Nuevo estado del ciclo.
        db: Sesión de BD.

    Returns:
        `FiscalYearOut` actualizado.

    Raises:
        HTTPException: 404 si no hay `Taxpayer` o no existe ese 年度.
    """
    taxpayer = get_taxpayer(db)
    if taxpayer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "no_taxpayer",
                "message": "納税者が登録されていません。",
                "details": {},
            },
        )
    fy = set_fiscal_year_status(db, taxpayer, year, payload.status)
    if fy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "no_fiscal_year",
                "message": f"{year}年度が見つかりませんでした。",
                "details": {"year": year},
            },
        )
    db.commit()
    db.refresh(fy)
    return _fiscal_year_out(fy)


@router.get(
    "/fiscal-years/{year}/opening-balances",
    response_model=OpeningBalanceSummary,
)
def get_opening_balances(
    year: int = Path(ge=2000, le=2100), db: Session = Depends(get_db)
) -> OpeningBalanceSummary:
    """Devuelve los 期首残高 manuales del 年度.

    Args:
        year: Año fiscal.
        db: Sesión de BD.

    Returns:
        Resumen de saldos de apertura y totales de balance.
    """
    fy = _resolve_year(db, year)
    return _opening_summary(db, fy)


@router.post(
    "/fiscal-years/{year}/opening-balances",
    response_model=OpeningBalanceSummary,
)
def upsert_opening_balances(
    payload: OpeningBalanceUpsert,
    year: int = Path(ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> OpeningBalanceSummary:
    """Reemplaza los saldos iniciales manuales del 年度.

    El payload debe cuadrar ``資産 = 負債 + 資本``. Si cuadra, se persisten los
    saldos y se recrea el 仕訳 de apertura para que el balance sheet lo incluya.
    Un payload vacío o todo en cero borra los saldos existentes.
    """
    fy = _resolve_year(db, year)
    require_open_fiscal_year(fy)

    seen: set[str] = set()
    duplicates: set[str] = set()
    for line in payload.balances:
        code = line.account_code.strip()
        if code in seen:
            duplicates.add(code)
        seen.add(code)
        line.account_code = code
    if duplicates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "duplicate_account_code",
                "message": "同じ勘定科目が重複しています。",
                "details": {"account_codes": sorted(duplicates)},
            },
        )

    accounts = _accounts_by_code(db, set(seen))
    total_assets, total_liabilities, total_equity = _totals(payload.balances, accounts)
    imbalance = total_assets - total_liabilities - total_equity
    if imbalance != 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "opening_balance_unbalanced",
                "message": "期首残高が一致しません。資産 = 負債 + 資本 にしてください。",
                "details": {
                    "total_assets": total_assets,
                    "total_liabilities": total_liabilities,
                    "total_equity": total_equity,
                    "imbalance": imbalance,
                },
            },
        )

    _delete_existing_opening_balance(db, fy)
    db.flush()

    nonzero = [line for line in payload.balances if line.amount > 0]
    for line in nonzero:
        db.add(
            OpeningBalance(
                fiscal_year_id=fy.id,
                account_id=accounts[line.account_code].id,
                amount=line.amount,
            )
        )

    if nonzero:
        entry = JournalEntry(
            fiscal_year_id=fy.id,
            date=date(year, 1, 1),
            description=OPENING_BALANCE_DESCRIPTION,
            created_by=OPENING_BALANCE_CREATED_BY,
        )
        for line in nonzero:
            account = accounts[line.account_code]
            category = AccountCategory(account.category)
            entry.lines.append(
                JournalLine(
                    side=(
                        JournalSide.DEBIT
                        if category == AccountCategory.ASSET
                        else JournalSide.CREDIT
                    ),
                    account_id=account.id,
                    amount=line.amount,
                )
            )
        post_entry(db, entry, commit=False)

    db.commit()
    return _opening_summary(db, fy)
