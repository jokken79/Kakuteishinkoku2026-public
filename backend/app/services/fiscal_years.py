"""Service del ciclo multi-año fiscal (年度).

Centraliza la lógica de gestión de `FiscalYear` para que la app funcione año
tras año (2025, 2026, 2027...) sin tocar código:

- Listar los 年度 del contribuyente (year + status), ordenados desc.
- Asegurar (idempotente) el 年度 de un año dado (crea si falta).
- Resolver el 年度 "activo" por defecto: el OPEN más reciente.
- Cambiar el status de un 年度 (open/closed/filed).

Diseño single-user (MVP): hay un único `Taxpayer`. Toda la lógica opera sobre
ese contribuyente. La fuente de verdad del estado del ciclo es el campo `status`
del `FiscalYear` (enum `FiscalYearStatus`).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import FiscalYear, Taxpayer
from app.models.enums import FiscalYearStatus

logger = logging.getLogger(__name__)


def get_taxpayer(db: Session) -> Taxpayer | None:
    """Devuelve el (único) `Taxpayer` del MVP single-user, o ``None``.

    Args:
        db: Sesión de BD.

    Returns:
        El `Taxpayer` registrado, o ``None`` si aún no hay ninguno.
    """
    return db.scalars(select(Taxpayer)).first()


def ensure_fiscal_year(db: Session, taxpayer: Taxpayer, year: int) -> FiscalYear:
    """Devuelve el `FiscalYear` del año (idempotente; lo crea si falta).

    Si ya existe un 年度 para ``(taxpayer, year)`` lo devuelve tal cual (no toca
    su status). Si no existe, lo crea en estado ``OPEN``.

    Args:
        db: Sesión de BD.
        taxpayer: Contribuyente dueño del 年度.
        year: Año fiscal (西暦, ej. 2025).

    Returns:
        El `FiscalYear` asegurado (flush, sin commit).
    """
    fy = db.scalars(
        select(FiscalYear).where(
            FiscalYear.taxpayer_id == taxpayer.id, FiscalYear.year == year
        )
    ).first()
    if fy is None:
        fy = FiscalYear(
            taxpayer_id=taxpayer.id,
            year=year,
            rules_ref=str(year),
            status=FiscalYearStatus.OPEN,
        )
        db.add(fy)
        db.flush()
        logger.info("FiscalYear creado taxpayer=%s year=%s", taxpayer.id, year)
    return fy


def list_fiscal_years(db: Session, taxpayer: Taxpayer) -> list[FiscalYear]:
    """Lista los 年度 del contribuyente, ordenados por año descendente.

    Args:
        db: Sesión de BD.
        taxpayer: Contribuyente.

    Returns:
        Lista de `FiscalYear` (más reciente primero).
    """
    return list(
        db.scalars(
            select(FiscalYear)
            .where(FiscalYear.taxpayer_id == taxpayer.id)
            .order_by(FiscalYear.year.desc())
        ).all()
    )


def resolve_active_fiscal_year(
    db: Session, taxpayer: Taxpayer | None = None
) -> FiscalYear | None:
    """Resuelve el 年度 "activo" por defecto: el OPEN más reciente.

    Si no hay ningún 年度 OPEN, cae al 年度 más reciente sea cual sea su status
    (para no dejar al usuario sin contexto). Devuelve ``None`` si el
    contribuyente aún no tiene ningún 年度.

    Args:
        db: Sesión de BD.
        taxpayer: Contribuyente; si es ``None`` se resuelve el único del MVP.

    Returns:
        El `FiscalYear` activo por defecto, o ``None``.
    """
    tp = taxpayer or get_taxpayer(db)
    if tp is None:
        return None
    open_fy = db.scalars(
        select(FiscalYear)
        .where(
            FiscalYear.taxpayer_id == tp.id,
            FiscalYear.status == FiscalYearStatus.OPEN,
        )
        .order_by(FiscalYear.year.desc())
    ).first()
    if open_fy is not None:
        return open_fy
    return db.scalars(
        select(FiscalYear)
        .where(FiscalYear.taxpayer_id == tp.id)
        .order_by(FiscalYear.year.desc())
    ).first()


def set_fiscal_year_status(
    db: Session, taxpayer: Taxpayer, year: int, new_status: FiscalYearStatus
) -> FiscalYear | None:
    """Cambia el status de un 年度 existente (open/closed/filed).

    Args:
        db: Sesión de BD.
        taxpayer: Contribuyente dueño del 年度.
        year: Año fiscal a modificar.
        new_status: Nuevo estado del ciclo.

    Returns:
        El `FiscalYear` actualizado, o ``None`` si no existe ese año.
    """
    fy = db.scalars(
        select(FiscalYear).where(
            FiscalYear.taxpayer_id == taxpayer.id, FiscalYear.year == year
        )
    ).first()
    if fy is None:
        return None
    fy.status = new_status
    db.flush()
    logger.info(
        "FiscalYear status taxpayer=%s year=%s -> %s", taxpayer.id, year, new_status
    )
    return fy
