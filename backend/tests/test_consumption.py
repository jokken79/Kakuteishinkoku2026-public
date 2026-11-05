"""Tests del motor de 消費税 (`app.domain.tax.consumption`).

Cada test documenta el calculo manual paso a paso (割戻し計算, 区分経理, みなし仕入率,
2割/3割特例) para trazabilidad contra el 作成コーナー del NTA (令和7年分).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.tax.consumption import (
    calculate_consumption_tax,
)
from app.models.entities import IncomeSource, Transaction
from app.models.enums import IncomeType, TransactionStatus
from app.services.tax_rules import load_tax_rules


@pytest.fixture
def crules():
    """Parametros del 消費税 2025 (令和7)."""
    return load_tax_rules(2025).consumption


def _jigyo(gross: int, reduced_ratio: float = 0.0) -> IncomeSource:
    """Crea una fila 事業 (売上 税込) con la proporcion 8% indicada."""
    meta = {"consumption": {"reduced_ratio": reduced_ratio}} if reduced_ratio else None
    return IncomeSource(
        fiscal_year_id=None,
        income_type=IncomeType.JIGYO,
        gross=gross,
        withholding=0,
        meta=meta,
    )


def _expense(total: int, rate: int, qualified: bool) -> Transaction:
    """Crea un gasto confirmado 税込 con su 区分経理 y flag 適格請求書."""
    base = round(total / (1 + rate / 100))
    return Transaction(
        fiscal_year_id=None,
        date=date(2025, 5, 1),
        total_amount=total,
        source="manual",
        is_qualified_invoice=qualified,
        status=TransactionStatus.CONFIRMED,
        tax_lines=[{"base": base, "tax": total - base, "rate": rate}],
    )


def test_sales_tax_all_10pct(crules) -> None:
    """売上税額: ¥11,000,000 税込 (todo 10%) -> 国税 ¥780,000 (割戻し 7.8/110)."""
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[],
        is_taxable=True,
        method_setting="honsoku",
        business_category=None,
        is_individual=True,
        rules=crules,
        as_of=date(2025, 12, 31),
    )
    # 11,000,000 × 7.8/110 = 780,000.
    assert result.sales_breakdown.national_tax_10 == 780_000
    assert result.sales_breakdown.national_tax_8 == 0
    assert result.sales_breakdown.national_tax_total == 780_000


def test_sales_tax_split_8_and_10(crules) -> None:
    """区分経理 del 売上: 20% al 軽減8%, 80% al 10%.

    売上 ¥10,000,000 税込: 8% = ¥2,000,000, 10% = ¥8,000,000.
      国税8% = 2,000,000 × 6.24/108 = 115,555.
      国税10% = 8,000,000 × 7.8/110 = 567,272.
    """
    result = calculate_consumption_tax(
        sources=[_jigyo(10_000_000, reduced_ratio=0.2)],
        confirmed=[],
        is_taxable=True,
        method_setting="honsoku",
        business_category=None,
        is_individual=True,
        rules=crules,
        as_of=date(2025, 12, 31),
    )
    assert result.sales_breakdown.taxable_sales_8 == 2_000_000
    assert result.sales_breakdown.taxable_sales_10 == 8_000_000
    assert result.sales_breakdown.national_tax_8 == int(2_000_000 * 6.24 / 108)
    assert result.sales_breakdown.national_tax_10 == int(8_000_000 * 7.8 / 110)


def test_honsoku_only_qualified_invoices_deductible(crules) -> None:
    """本則課税: solo los gastos con 適格請求書 dan 仕入税額控除.

    売上 ¥11,000,000 -> 売上税額(国税) ¥780,000.
    Gasto適格 ¥1,100,000 (10%) -> 国税 ¥78,000 (deducible).
    Gasto NO適格 ¥550,000 -> excluido del control.
      差引(国税) = 780,000 − 78,000 = 702,000.
      地方 = 702,000 × 22/78 = 198,000.
      納付税額 = 702,000 + 198,000 = ¥900,000.
    """
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[
            _expense(1_100_000, 10, qualified=True),
            _expense(550_000, 10, qualified=False),
        ],
        is_taxable=True,
        method_setting="honsoku",
        business_category=None,
        is_individual=True,
        rules=crules,
        as_of=date(2025, 12, 31),
    )
    assert result.purchase_breakdown.national_tax_total == 78_000
    assert result.purchase_breakdown.excluded_non_qualified == 550_000
    assert result.honsoku.purchase_tax_credit == 78_000
    assert result.honsoku.national_tax == 702_000
    assert result.honsoku.local_tax == 198_000
    assert result.honsoku.total_tax == 900_000


def test_kani_deemed_purchase_rate_per_category(crules) -> None:
    """簡易課税: 仕入税額控除 = 売上税額 × みなし仕入率 segun 事業区分.

    売上税額(国税) ¥780,000.
      第5種 (サービス 50%): 控除 = 780,000 × 0.5 = 390,000.
      差引 = 390,000; 地方 = 390,000 × 22/78 = 110,000; 納付 = 500,000.
    """
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[],
        is_taxable=True,
        method_setting="kani",
        business_category=5,
        is_individual=True,
        rules=crules,
        as_of=date(2025, 12, 31),
    )
    assert result.kani.eligible is False
    assert result.kani.eligibility_status == "unverified"
    assert result.kani.purchase_tax_credit == 390_000
    assert result.kani.national_tax == 390_000
    assert result.kani.local_tax == 110_000
    assert result.kani.total_tax == 500_000


def test_mixed_expense_credits_only_business_part(crules) -> None:
    tx = _expense(700_000, 10, qualified=True)
    tx.business_allocation = {"original_total": 700_000, "numerator": 3, "denominator": 10}
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)], confirmed=[tx], is_taxable=True,
        method_setting=None, business_category=None, is_individual=True,
        rules=crules, as_of=date(2025, 12, 31),
    )
    assert result.purchase_breakdown.qualified_purchases_10 == 210_000
    assert tx.total_amount == 700_000


def test_mixed_expense_excludes_zero_rate_from_consumption_credit(crules) -> None:
    tx = _expense(1_100, 10, qualified=True)
    tx.total_amount = 2_100
    tx.tax_lines = [{"base": 1_000, "tax": 100, "rate": 10},
                    {"base": 1_000, "tax": 0, "rate": 0}]
    tx.business_allocation = {"original_total": 2_100, "numerator": 1, "denominator": 2}
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)], confirmed=[tx], is_taxable=True,
        method_setting=None, business_category=None, is_individual=True,
        rules=crules, as_of=date(2025, 12, 31),
    )
    assert result.purchase_breakdown.qualified_purchases_10 == 550
    assert result.purchase_breakdown.qualified_purchases_8 == 0


def test_kani_categories_table(crules) -> None:
    """みなし仕入率 por 事業区分 (第1〜6種): 90/80/70/60/50/40%."""
    expected = {1: 0.90, 2: 0.80, 3: 0.70, 4: 0.60, 5: 0.50, 6: 0.40}
    sales_tax = 780_000  # 11M × 7.8/110.
    for category, rate in expected.items():
        result = calculate_consumption_tax(
            sources=[_jigyo(11_000_000)],
            confirmed=[],
            is_taxable=True,
            method_setting="kani",
            business_category=category,
            is_individual=True,
            rules=crules,
            as_of=date(2025, 12, 31),
        )
        assert result.kani.purchase_tax_credit == int(sales_tax * rate), category


def test_kani_not_eligible_without_category(crules) -> None:
    """簡易課税 sin 事業区分: no es elegible (queda fuera del comparador)."""
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[],
        is_taxable=True,
        method_setting="kani",
        business_category=None,
        is_individual=True,
        rules=crules,
        as_of=date(2025, 12, 31),
    )
    assert result.kani.eligible is False


def test_tokurei_2wari(crules) -> None:
    """2割特例: 仕入税額控除 = 売上税額 × 80% (paga el 20%).

    売上税額(国税) ¥780,000.
      控除 = 780,000 × 0.8 = 624,000.
      差引 = 156,000; 地方 = 156,000 × 22/78 = 44,000; 納付 = 200,000.
    """
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[],
        is_taxable=True,
        method_setting="tokurei_2wari",
        business_category=None,
        is_individual=True,
        rules=crules,
        as_of=date(2025, 12, 31),
    )
    assert result.tokurei.label == "2割特例"
    assert result.tokurei.purchase_tax_credit == 624_000
    assert result.tokurei.national_tax == 156_000
    assert result.tokurei.local_tax == 44_000
    assert result.tokurei.total_tax == 200_000


def test_tokurei_changes_by_annual_fiscal_period(crules) -> None:
    """2026 conserva 2割 para todo el año; 2027 y 2028 aplican 3割."""
    before = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[],
        is_taxable=True,
        method_setting="tokurei_2wari",
        business_category=None,
        is_individual=True,
        rules=crules.model_copy(update={"year": 2026}),
        as_of=date(2026, 12, 31),
    )
    after = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[],
        is_taxable=True,
        method_setting="tokurei_2wari",
        business_category=None,
        is_individual=True,
        rules=crules.model_copy(update={"year": 2027}),
        as_of=date(2027, 12, 31),
    )
    assert before.tokurei.label == "2割特例"
    assert before.tokurei.purchase_tax_credit == int(780_000 * 0.8)
    assert after.tokurei.label == "3割特例"
    assert after.tokurei.purchase_tax_credit == int(780_000 * 0.7)

    expired = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[],
        is_taxable=True,
        method_setting="tokurei_2wari",
        business_category=None,
        is_individual=True,
        rules=crules.model_copy(update={"year": 2029}),
        as_of=date(2029, 12, 31),
    )
    assert not expired.tokurei.eligible


def test_comparator_does_not_recommend_unverified_methods(crules) -> None:
    """Una simulación barata no demuestra que el régimen pueda aplicarse."""
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[],
        is_taxable=True,
        method_setting="honsoku",
        business_category=5,
        is_individual=True,
        rules=crules,
        as_of=date(2025, 12, 31),
    )
    assert result.recommended is None
    assert result.honsoku.total_tax == 1_000_000
    assert result.recommended_saving == 0
    assert all(o.eligibility_status == "unverified" and not o.eligible for o in
               (result.honsoku, result.kani, result.tokurei))


def test_comparator_can_recommend_honsoku_with_many_invoices(crules) -> None:
    """本則 puede ser la mejor opcion si hay muchos gastos con 適格請求書.

    売上 ¥11,000,000 -> 売上税額 ¥780,000.
    Gasto適格 ¥9,900,000 (10%) -> 国税 = 9,900,000 × 7.8/110 = 702,000.
      本則: 差引 = 780,000 − 702,000 = 78,000 -> mucho menor que 簡易/特例.
    """
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[_expense(9_900_000, 10, qualified=True)],
        is_taxable=True,
        method_setting="honsoku",
        business_category=5,
        is_individual=True,
        rules=crules,
        as_of=date(2025, 12, 31),
    )
    assert result.honsoku.purchase_tax_credit == 702_000
    assert result.recommended is None


def test_menzei_returns_empty(crules) -> None:
    """免税事業者: is_taxable False, sin recomendacion (declaracion no necesaria)."""
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[],
        is_taxable=False,
        method_setting=None,
        business_category=None,
        is_individual=True,
        rules=crules,
        as_of=date(2025, 12, 31),
    )
    assert result.is_taxable is False
    assert result.recommended is None
    assert result.recommended_saving == 0


def test_tokurei_not_eligible_for_corporation(crules) -> None:
    """2割特例 es SOLO para 個人: una 法人 (is_individual False) no es elegible."""
    result = calculate_consumption_tax(
        sources=[_jigyo(11_000_000)],
        confirmed=[],
        is_taxable=True,
        method_setting="honsoku",
        business_category=None,
        is_individual=False,
        rules=crules,
        as_of=date(2025, 12, 31),
    )
    assert result.tokurei.eligible is False
