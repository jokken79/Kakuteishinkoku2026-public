"""Tests del calculo de las 所得控除 (`app.domain.tax.deductions`)."""

import pytest

from app.domain.tax.deduction_service import total_tax_credits
from app.domain.tax.deductions import (
    compute_deductions,
    dependent_deduction,
    earthquake_insurance_deduction,
    furusato_deduction,
    kiso_deduction,
    life_insurance_deduction,
    medical_deduction,
)
from app.domain.tax.schemas import DeductionInput, Dependent, DependentKind
from app.models.entities import Deduction
from app.models.enums import DeductionType
from app.services.tax_rules import load_tax_rules


@pytest.fixture
def rules():
    """Parametros fiscales 2025."""
    return load_tax_rules(2025)


def test_kiso_deduction_escalonado(rules) -> None:
    """基礎控除 escalonado por 合計所得 (令和7)."""
    assert kiso_deduction(1_000_000, rules) == 950_000
    assert kiso_deduction(5_000_000, rules) == 630_000
    assert kiso_deduction(10_000_000, rules) == 580_000
    assert kiso_deduction(30_000_000, rules) == 0


def test_medical_deduction_floor_100k(rules) -> None:
    """医療費控除: piso ¥100k cuando 総所得×5% >= 100k.

    総所得 5M -> 5% = 250k > 100k, asi que piso = 100k.
    (gasto 300k − reembolso 0) − 100k = 200,000.
    """
    assert medical_deduction(300_000, 0, 5_000_000, rules) == 200_000


def test_medical_deduction_floor_5pct(rules) -> None:
    """医療費控除: piso 総所得×5% cuando es menor a ¥100k.

    総所得 1M -> 5% = 50k < 100k, piso = 50k.
    (200k − 0) − 50k = 150,000.
    """
    assert medical_deduction(200_000, 0, 1_000_000, rules) == 150_000


def test_medical_deduction_reimbursement_and_zero(rules) -> None:
    """医療費控除 resta reembolso y no baja de 0."""
    # (120k − 50k) − min(100k, 5M*5%) = 70k − 100k < 0 -> 0.
    assert medical_deduction(120_000, 50_000, 5_000_000, rules) == 0


def test_medical_deduction_cap(rules) -> None:
    """医療費控除 con tope ¥2,000,000."""
    # gasto enorme, 総所得 alto: piso 100k. 2.5M - 100k = 2.4M -> cap 2M.
    assert medical_deduction(2_500_000, 0, 10_000_000, rules) == 2_000_000


def test_life_insurance_cap(rules) -> None:
    """生命保険料控除 acotado al tope ¥120,000."""
    assert life_insurance_deduction(80_000, rules) == 80_000
    assert life_insurance_deduction(200_000, rules) == 120_000


def test_earthquake_insurance_cap(rules) -> None:
    """地震保険料控除 acotado al tope ¥50,000."""
    assert earthquake_insurance_deduction(30_000, rules) == 30_000
    assert earthquake_insurance_deduction(80_000, rules) == 50_000


def test_dependent_deduction_by_kind() -> None:
    """扶養控除 suma el monto por categoria."""
    deps = [
        Dependent(kind=DependentKind.GENERAL),  # 380k
        Dependent(kind=DependentKind.SPECIFIC),  # 630k
        Dependent(kind=DependentKind.ELDERLY),  # 480k
        Dependent(kind=DependentKind.ELDERLY_COHABITING),  # 580k
    ]
    assert dependent_deduction(deps) == 2_070_000


def test_dependent_deduction_unmapped_kind_is_zero(monkeypatch) -> None:
    """Una categoria sin monto en la tabla aporta 0, no revienta con KeyError.

    Hardening: si `DependentKind` se extiende y `DEPENDENT_AMOUNTS` no mapea el
    nuevo valor, el cálculo del 確定申告 NO debe explotar — el `.get(..., 0)` lo
    trata como sin 控除. Simulamos el caso quitando una clave del mapa.
    """
    from app.domain.tax import deductions as ded_mod

    patched = dict(ded_mod.DEPENDENT_AMOUNTS)
    del patched[DependentKind.ELDERLY]  # simula categoria sin monto mapeado
    monkeypatch.setattr(ded_mod, "DEPENDENT_AMOUNTS", patched)

    deps = [
        Dependent(kind=DependentKind.GENERAL),  # 380k
        Dependent(kind=DependentKind.ELDERLY),  # sin mapeo -> 0
    ]
    # No lanza KeyError; el no-mapeado suma 0.
    assert ded_mod.dependent_deduction(deps) == 380_000


def test_furusato_deduction(rules) -> None:
    """寄附金控除: (donado − ¥2,000), tope 40% del 総所得."""
    # donado 50k, 総所得 5M (tope 2M). 50k − 2k = 48,000.
    assert furusato_deduction(50_000, 5_000_000, rules) == 48_000
    # donado <= floor -> 0.
    assert furusato_deduction(2_000, 5_000_000, rules) == 0
    # tope del 40%: total_income 100k -> cap 40k. min(50k,40k)-2k = 38,000.
    assert furusato_deduction(50_000, 100_000, rules) == 38_000


def test_compute_deductions_total_and_breakdown(rules) -> None:
    """compute_deductions agrega total + desglose.

    Caso: 総所得 5M, 社会保険 600k, sin otras deducciones.
    基礎控除 = 630k (tramo 4.89M-6.55M). total = 630k + 600k = 1,230,000.
    """
    deductions = DeductionInput(social_insurance=600_000)
    breakdown, total = compute_deductions(deductions, 5_000_000, rules)
    assert breakdown.kiso == 630_000
    assert breakdown.social_insurance == 600_000
    assert total == 1_230_000


def test_rejected_housing_loan_is_not_applied() -> None:
    """Un crédito rechazado queda en historial, pero aporta ¥0 al cálculo."""
    rejected = Deduction(
        type=DeductionType.HOUSING_LOAN,
        amount=39_000,
        meta={"claim_status": "rejected"},
    )
    assert total_tax_credits([rejected]) == 0


def test_approved_housing_loan_is_applied() -> None:
    """El crédito solo se suma cuando está aprobado/aplicado."""
    approved = Deduction(
        type=DeductionType.HOUSING_LOAN,
        amount=39_000,
        meta={"claim_status": "approved"},
    )
    assert total_tax_credits([approved]) == 39_000
