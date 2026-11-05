"""Router de 家計簿 — libro de gastos personales (NO fiscal).

Módulo 100% ADITIVO: trackea gastos PERSONALES que NO van a la declaración.
Los `HouseholdExpense` NUNCA entran al 仕訳 ni al cálculo del 所得税/住民税/消費税.

Endpoints (bajo `/api/v1`):

- ``POST   /household``                  — crea un gasto personal manual.
- ``GET    /household?year=&month=``     — lista los gastos de un mes.
- ``GET    /household/summary?year=&month=`` — total + desglose por 費目 del mes.
- ``PATCH  /household/{id}``             — edita un gasto.
- ``DELETE /household/{id}``             — borra un gasto.
- ``POST   /household/from-transaction/{tx_id}`` — mueve un ítem del 仕訳トレイ
  al 家計簿 (lo marca 家計, lo saca del flujo del negocio).
"""

from __future__ import annotations

import datetime as _dt
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.household import (
    CategoryTotal,
    list_expenses,
    summarize_month,
)
from app.models.entities import HouseholdExpense, Transaction
from app.models.enums import HouseholdCategory, TransactionStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["household"])


# --- Schemas ---------------------------------------------------------------


class HouseholdExpenseOut(BaseModel):
    """Un gasto personal del 家計簿 (registro persistido)."""

    id: uuid.UUID
    date: _dt.date
    amount: int
    category: HouseholdCategory
    memo: str | None
    created_at: _dt.datetime


class HouseholdExpenseCreate(BaseModel):
    """Alta manual de un gasto personal."""

    date: _dt.date
    amount: int = Field(gt=0, description="Monto en yenes (entero positivo).")
    category: HouseholdCategory
    memo: str | None = Field(default=None, max_length=255)


class HouseholdExpensePatch(BaseModel):
    """Campos editables de un gasto personal (solo los provistos)."""

    date: _dt.date | None = None
    amount: int | None = Field(default=None, gt=0)
    category: HouseholdCategory | None = None
    memo: str | None = Field(default=None, max_length=255)


class CategoryTotalOut(BaseModel):
    """Total de un 費目 dentro de un mes."""

    category: HouseholdCategory
    total: int
    count: int


class HouseholdSummaryOut(BaseModel):
    """Resumen mensual del 家計簿: total + desglose por 費目."""

    year: int
    month: int
    total: int
    by_category: list[CategoryTotalOut]


# --- Helpers ---------------------------------------------------------------


def _to_out(expense: HouseholdExpense) -> HouseholdExpenseOut:
    """Serializa un `HouseholdExpense` a `HouseholdExpenseOut`."""
    return HouseholdExpenseOut(
        id=expense.id,
        date=expense.date,
        amount=expense.amount,
        category=expense.category,
        memo=expense.memo,
        created_at=expense.created_at,
    )


def _category_out(total: CategoryTotal) -> CategoryTotalOut:
    """Serializa un `CategoryTotal` del dominio a su DTO."""
    return CategoryTotalOut(
        category=total.category,
        total=total.total,
        count=total.count,
    )


def _get_or_404(db: Session, expense_id: uuid.UUID) -> HouseholdExpense:
    """Devuelve el gasto o lanza 404."""
    expense = db.get(HouseholdExpense, expense_id)
    if expense is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": "家計簿の支出が見つかりませんでした。",
                "details": {},
            },
        )
    return expense


# --- Endpoints -------------------------------------------------------------


@router.post(
    "/household",
    response_model=HouseholdExpenseOut,
    status_code=status.HTTP_201_CREATED,
)
def create_expense(
    payload: HouseholdExpenseCreate, db: Session = Depends(get_db)
) -> HouseholdExpenseOut:
    """Crea un gasto personal manual en el 家計簿.

    Args:
        payload: Datos del gasto (fecha, monto, 費目, memo opcional).
        db: Sesión de BD.

    Returns:
        `HouseholdExpenseOut` recién creada.
    """
    expense = HouseholdExpense(
        date=payload.date,
        amount=payload.amount,
        category=payload.category,
        memo=payload.memo,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return _to_out(expense)


@router.get("/household", response_model=list[HouseholdExpenseOut])
def list_household_expenses(
    year: int = Query(..., ge=1989, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> list[HouseholdExpenseOut]:
    """Lista los gastos personales de un mes (más recientes primero).

    Args:
        year: Año gregoriano.
        month: Mes (1-12).
        db: Sesión de BD.

    Returns:
        Lista de `HouseholdExpenseOut` del mes.
    """
    expenses = list_expenses(db, year=year, month=month)
    return [_to_out(e) for e in expenses]


@router.get("/household/summary", response_model=HouseholdSummaryOut)
def household_summary(
    year: int = Query(..., ge=1989, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> HouseholdSummaryOut:
    """Devuelve el total del mes y el desglose por 費目.

    Args:
        year: Año gregoriano.
        month: Mes (1-12).
        db: Sesión de BD.

    Returns:
        `HouseholdSummaryOut` con el total general y el total por categoría.
    """
    summary = summarize_month(db, year=year, month=month)
    return HouseholdSummaryOut(
        year=summary.year,
        month=summary.month,
        total=summary.total,
        by_category=[_category_out(c) for c in summary.by_category],
    )


@router.patch("/household/{expense_id}", response_model=HouseholdExpenseOut)
def patch_expense(
    expense_id: uuid.UUID,
    patch: HouseholdExpensePatch,
    db: Session = Depends(get_db),
) -> HouseholdExpenseOut:
    """Edita un gasto personal (solo los campos provistos).

    Args:
        expense_id: Id del gasto.
        patch: Campos a actualizar.
        db: Sesión de BD.

    Returns:
        `HouseholdExpenseOut` actualizada.
    """
    expense = _get_or_404(db, expense_id)
    data = patch.model_dump(exclude_unset=True)
    for field_name, value in data.items():
        setattr(expense, field_name, value)
    db.commit()
    db.refresh(expense)
    return _to_out(expense)


@router.delete(
    "/household/{expense_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_expense(
    expense_id: uuid.UUID, db: Session = Depends(get_db)
) -> None:
    """Borra un gasto personal del 家計簿.

    Args:
        expense_id: Id del gasto.
        db: Sesión de BD.
    """
    expense = _get_or_404(db, expense_id)
    db.delete(expense)
    db.commit()


# --- Puente 事業 / 家計 (Parte 3) ------------------------------------------


class FromTransactionRequest(BaseModel):
    """Datos para mover un ítem del 仕訳トレイ al 家計簿."""

    category: HouseholdCategory = Field(
        default=HouseholdCategory.SONOTA,
        description="費目 al que se asigna el gasto personal.",
    )


@router.post(
    "/household/from-transaction/{transaction_id}",
    response_model=HouseholdExpenseOut,
    status_code=status.HTTP_201_CREATED,
)
def from_transaction(
    transaction_id: uuid.UUID,
    payload: FromTransactionRequest,
    db: Session = Depends(get_db),
) -> HouseholdExpenseOut:
    """Marca un ítem del 仕訳トレイ como 家計 (gasto personal).

    Crea un `HouseholdExpense` a partir de la transacción y la saca del flujo
    del negocio marcándola como ``rejected`` (no entra al 仕訳 ni a la
    declaración). Es el puente 事業 → 家計 de la bandeja de revisión.

    Args:
        transaction_id: Id de la transacción pendiente.
        payload: 費目 destino del gasto personal.
        db: Sesión de BD.

    Returns:
        `HouseholdExpenseOut` del gasto personal creado.

    Raises:
        HTTPException: 404 si la transacción no existe.
    """
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": "取引が見つかりませんでした。",
                "details": {},
            },
        )

    expense = HouseholdExpense(
        date=tx.date,
        amount=tx.total_amount,
        category=payload.category,
        memo=tx.vendor,
    )
    db.add(expense)
    # Sacar del flujo del negocio: rechazada => no aparece en la bandeja de 仕訳.
    tx.status = TransactionStatus.REJECTED
    db.commit()
    db.refresh(expense)
    return _to_out(expense)
