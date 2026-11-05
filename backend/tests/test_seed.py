"""Tests del seed de 勘定科目 y del mapeo vendor -> 科目."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Account
from app.models.enums import AccountCategory
from app.seed.accounts import DEFAULT_ACCOUNTS, seed_accounts
from app.seed.vendor_mapping import classify_vendor


def test_seed_inserts_expected_accounts(session: Session) -> None:
    """seed_accounts inserta todas las cuentas estandar esperadas."""
    created = seed_accounts(session)
    assert len(created) == len(DEFAULT_ACCOUNTS)

    total = session.scalar(select(func.count()).select_from(Account))
    assert total == len(DEFAULT_ACCOUNTS)

    names = set(session.scalars(select(Account.name)).all())
    for expected in ("現金", "普通預金", "売上高", "旅費交通費", "消耗品費", "通信費",
                     "元入金", "事業主貸", "事業主借", "減価償却費", "雑費"):
        assert expected in names, f"falta la cuenta {expected}"


def test_seed_categories_correct(session: Session) -> None:
    """Cada cuenta semilla tiene la categoria contable correcta."""
    seed_accounts(session)
    by_name = {a.name: a for a in session.scalars(select(Account)).all()}
    assert by_name["現金"].category == AccountCategory.ASSET
    assert by_name["普通預金"].category == AccountCategory.ASSET
    assert by_name["売上高"].category == AccountCategory.REVENUE
    assert by_name["旅費交通費"].category == AccountCategory.EXPENSE
    assert by_name["元入金"].category == AccountCategory.EQUITY
    assert by_name["事業主貸"].category == AccountCategory.EQUITY
    assert by_name["買掛金"].category == AccountCategory.LIABILITY


def test_seed_is_idempotent(session: Session) -> None:
    """Correr seed dos veces no duplica cuentas."""
    seed_accounts(session)
    second = seed_accounts(session)
    assert second == []
    total = session.scalar(select(func.count()).select_from(Account))
    assert total == len(DEFAULT_ACCOUNTS)


def test_classify_vendor_known_mappings() -> None:
    """El mapeo vendor -> codigo de cuenta clasifica vendors conocidos."""
    # 旅費交通費 = 501
    assert classify_vendor("JR東日本") == "501"
    assert classify_vendor("個人タクシー") == "501"
    assert classify_vendor("ETCマイレージ") == "501"
    # 通信費 = 505
    assert classify_vendor("NTTドコモ") == "505"
    assert classify_vendor("日本郵便") == "505"
    # 消耗品費 = 502
    assert classify_vendor("Amazon.co.jp") == "502"
    # 会議費 = 504
    assert classify_vendor("スターバックスコーヒー") == "504"
    assert classify_vendor("大衆居酒屋てっぺん") == "504"
    # 新聞図書費 = 506
    assert classify_vendor("丸善書店") == "506"


def test_classify_vendor_unknown_returns_none() -> None:
    """Vendor sin regla y entrada vacia devuelven None."""
    assert classify_vendor("謎の店舗XYZ") is None
    assert classify_vendor(None) is None
    assert classify_vendor("") is None
