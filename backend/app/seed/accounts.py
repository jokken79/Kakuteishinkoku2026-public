"""Seed de 勘定科目 estandar para 個人事業主 (青色申告決算書).

Define el catalogo de cuentas por defecto con su categoria contable y la linea
del 決算書 (`tax_form_line`) cuando aplica, e inserta las que falten en la BD de
forma idempotente (no duplica si ya existen por `code`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Account
from app.models.enums import AccountCategory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountSeed:
    """Definicion de una cuenta semilla.

    Args:
        code: Codigo contable estable.
        name: Nombre japones del 勘定科目.
        category: Categoria contable.
        tax_form_line: Linea del 決算書 (opcional).
    """

    code: str
    name: str
    category: AccountCategory
    tax_form_line: str | None = None


# Catalogo estandar de 個人事業主. Codigos siguiendo convencion comun:
# 1xx 資産, 2xx 負債, 3xx 資本, 4xx 収益, 5xx 費用.
DEFAULT_ACCOUNTS: tuple[AccountSeed, ...] = (
    # --- 資産 (asset) ---
    AccountSeed("101", "現金", AccountCategory.ASSET),
    AccountSeed("102", "普通預金", AccountCategory.ASSET),
    AccountSeed("135", "売掛金", AccountCategory.ASSET),
    # --- 負債 (liability) ---
    AccountSeed("201", "買掛金", AccountCategory.LIABILITY),
    AccountSeed("205", "未払金", AccountCategory.LIABILITY),
    # --- 資本 (equity) ---
    AccountSeed("301", "元入金", AccountCategory.EQUITY),
    AccountSeed("311", "事業主貸", AccountCategory.EQUITY),
    AccountSeed("312", "事業主借", AccountCategory.EQUITY),
    # --- 収益 (revenue) ---
    AccountSeed("401", "売上高", AccountCategory.REVENUE, tax_form_line="売上(収入)金額"),
    AccountSeed("409", "雑収入", AccountCategory.REVENUE, tax_form_line="雑収入"),
    # --- 費用 (expense) ---
    AccountSeed("501", "旅費交通費", AccountCategory.EXPENSE, tax_form_line="旅費交通費"),
    AccountSeed("502", "消耗品費", AccountCategory.EXPENSE, tax_form_line="消耗品費"),
    AccountSeed("503", "接待交際費", AccountCategory.EXPENSE, tax_form_line="接待交際費"),
    AccountSeed("504", "会議費", AccountCategory.EXPENSE, tax_form_line="会議費"),
    AccountSeed("505", "通信費", AccountCategory.EXPENSE, tax_form_line="通信費"),
    AccountSeed("506", "新聞図書費", AccountCategory.EXPENSE, tax_form_line="新聞図書費"),
    AccountSeed("507", "地代家賃", AccountCategory.EXPENSE, tax_form_line="地代家賃"),
    AccountSeed("508", "水道光熱費", AccountCategory.EXPENSE, tax_form_line="水道光熱費"),
    AccountSeed("509", "広告宣伝費", AccountCategory.EXPENSE, tax_form_line="広告宣伝費"),
    AccountSeed("510", "支払手数料", AccountCategory.EXPENSE, tax_form_line="支払手数料"),
    AccountSeed("511", "租税公課", AccountCategory.EXPENSE, tax_form_line="租税公課"),
    AccountSeed("512", "減価償却費", AccountCategory.EXPENSE, tax_form_line="減価償却費"),
    AccountSeed("513", "外注工賃", AccountCategory.EXPENSE, tax_form_line="外注工賃"),
    AccountSeed("514", "損害保険料", AccountCategory.EXPENSE, tax_form_line="損害保険料"),
    AccountSeed("599", "雑費", AccountCategory.EXPENSE, tax_form_line="雑費"),
)


def seed_accounts(session: Session, *, commit: bool = True) -> list[Account]:
    """Inserta las cuentas estandar que falten (idempotente).

    Args:
        session: Sesion de SQLAlchemy.
        commit: Si ``True`` confirma la transaccion al finalizar.

    Returns:
        Lista de instancias `Account` creadas en esta llamada (las que ya
        existian no se devuelven).
    """
    existing_codes = set(session.scalars(select(Account.code)).all())
    created: list[Account] = []

    for seed in DEFAULT_ACCOUNTS:
        if seed.code in existing_codes:
            continue
        account = Account(
            code=seed.code,
            name=seed.name,
            category=seed.category,
            tax_form_line=seed.tax_form_line,
            is_default=True,
        )
        session.add(account)
        created.append(account)

    if created:
        session.flush()
        logger.info("Seed de 勘定科目: %d cuentas insertadas", len(created))
    else:
        logger.info("Seed de 勘定科目: sin cambios (ya existian todas)")

    if commit:
        session.commit()

    return created
