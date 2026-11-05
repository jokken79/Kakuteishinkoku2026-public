"""Tests del 扶養控除 detallado + 国外居住 (`app.domain.tax.dependents`) — research 08."""

from datetime import date

import pytest

from app.domain.tax.dependents import (
    DEPENDENT_INCOME_THRESHOLD,
    age_at_year_end,
    classify_dependent,
)
from app.domain.tax.schemas import (
    Cohabitation,
    DependentInput,
    DependentKind,
    OverseasExemptionReason,
    Residence,
)

YEAR = 2025


def _dep(**kwargs) -> DependentInput:
    """Construye un DependentInput con defaults razonables para los tests."""
    base = {"name": "テスト", "goukei_shotoku": 0}
    base.update(kwargs)
    return DependentInput(**base)


def test_missing_birth_or_income_never_assumes_a_deduction() -> None:
    missing_birth = classify_dependent(_dep(birth_date=None), YEAR)
    assert not missing_birth.qualifies
    assert missing_birth.disqualified_reason == "birth_date_unknown"
    missing_income = classify_dependent(
        _dep(birth_date=date(1954, 4, 7), goukei_shotoku=None), YEAR
    )
    assert not missing_income.qualifies
    assert missing_income.disqualified_reason == "income_unknown"
    confirmed_zero = classify_dependent(_dep(birth_date=date(1954, 4, 7), goukei_shotoku=0), YEAR)
    assert confirmed_zero.qualifies


@pytest.mark.parametrize(
    ("amount", "qualifies", "reason"),
    [(None, False, "remittance_unknown"), (379_999, False, "remittance_below_380k"),
     (380_000, True, None)],
)
def test_overseas_remittance_exception_requires_amount(
    amount: int | None, qualifies: bool, reason: str | None
) -> None:
    result = classify_dependent(_dep(
        birth_date=date(1980, 1, 1), residence=Residence.OVERSEAS,
        overseas_exemption=OverseasExemptionReason.REMITTANCE_380K,
        annual_remittance=amount,
    ), YEAR)
    assert result.qualifies is qualifies
    assert result.disqualified_reason == reason


def test_elderly_overseas_not_subject_to_380k_exception() -> None:
    result = classify_dependent(_dep(
        birth_date=date(1950, 1, 1), residence=Residence.OVERSEAS,
        overseas_exemption=OverseasExemptionReason.REMITTANCE_380K,
        annual_remittance=None,
    ), YEAR)
    assert result.qualifies
    assert "soukin_38man" not in result.required_documents


def test_age_at_year_end() -> None:
    """Edad al 31/12 del año fiscal (research 08)."""
    # Nacido 1955-03-10 -> al 2025-12-31 tiene 70.
    assert age_at_year_end(date(1955, 3, 10), 2025) == 70
    # Nacido 1955-12-31 -> al 2025-12-31 ya cumplio 70.
    assert age_at_year_end(date(1955, 12, 31), 2025) == 70
    # Nacido 2010-01-01 alcanza 16 el día anterior al cumpleaños.
    assert age_at_year_end(date(2010, 1, 1), 2025) == 16
    assert age_at_year_end(date(1956, 1, 1), 2025) == 70
    assert age_at_year_end(date(1956, 1, 2), 2025) == 69
    assert age_at_year_end(None, 2025) is None


@pytest.mark.parametrize(
    ("birth", "expected_kind", "expected_amount"),
    [
        # 一般 (16-18, 23-69).
        (date(1980, 1, 1), DependentKind.GENERAL, 380_000),
        # 特定 (19-22).
        (date(2004, 1, 1), DependentKind.SPECIFIC, 630_000),
        # 年少 (<16): sin 控除.
        (date(2012, 1, 1), DependentKind.YOUNG, 0),
    ],
)
def test_category_by_age_domestic(
    birth: date, expected_kind: DependentKind, expected_amount: int
) -> None:
    """Categoria por edad (国内居住)."""
    result = classify_dependent(_dep(birth_date=birth), YEAR)
    assert result.kind == expected_kind
    assert result.income_tax_amount == expected_amount


def test_elderly_cohabiting_vs_separate() -> None:
    """La categoría ampliada requiere confirmar los requisitos de 同居老親等."""
    birth = date(1950, 1, 1)  # 75 al 2025
    together = classify_dependent(
        _dep(birth_date=birth, cohabitation=Cohabitation.TOGETHER,
             eligible_cohabiting_ancestor=True), YEAR
    )
    assert together.kind == DependentKind.ELDERLY_COHABITING
    assert together.income_tax_amount == 580_000
    assert together.resident_tax_amount == 450_000

    separate = classify_dependent(
        _dep(birth_date=birth, cohabitation=Cohabitation.SEPARATE), YEAR
    )
    assert separate.kind == DependentKind.ELDERLY
    assert separate.income_tax_amount == 480_000
    assert separate.resident_tax_amount == 380_000
    for confirmed in (None, False):
        other = classify_dependent(_dep(birth_date=birth, cohabitation=Cohabitation.TOGETHER,
                                         eligible_cohabiting_ancestor=confirmed), YEAR)
        assert other.kind == DependentKind.ELDERLY
        assert other.income_tax_amount == 480_000


def test_income_over_threshold_disqualifies() -> None:
    """合計所得金額 > ¥580,000 (令和7) -> 対象外, sin 控除."""
    result = classify_dependent(
        _dep(birth_date=date(1980, 1, 1), goukei_shotoku=DEPENDENT_INCOME_THRESHOLD + 1),
        YEAR,
    )
    assert result.kind == DependentKind.NONE
    assert result.qualifies is False
    assert result.income_tax_amount == 0
    assert result.disqualified_reason == "income_over_threshold"
    # En el umbral exacto SI califica.
    ok = classify_dependent(
        _dep(birth_date=date(1980, 1, 1), goukei_shotoku=DEPENDENT_INCOME_THRESHOLD),
        YEAR,
    )
    assert ok.qualifies is True


@pytest.mark.parametrize(("year", "threshold"), [(2024, 480_000), (2025, 580_000), (2026, 620_000)])
def test_dependent_income_limit_changes_by_tax_year(year: int, threshold: int) -> None:
    birth = date(1954, 4, 7)
    assert classify_dependent(_dep(birth_date=birth, goukei_shotoku=threshold), year).qualifies
    assert not classify_dependent(
        _dep(birth_date=birth, goukei_shotoku=threshold + 1), year
    ).qualifies


def test_jigyo_senju_disqualifies() -> None:
    """事業専従者 -> 対象外."""
    result = classify_dependent(
        _dep(birth_date=date(1980, 1, 1), is_jigyo_senju=True), YEAR
    )
    assert result.kind == DependentKind.NONE
    assert result.disqualified_reason == "jigyo_senju"


def test_overseas_30_69_no_reason_disqualifies() -> None:
    """国外居住 30-69 sin motivo (留学/障害者/送金38万) -> NO califica (research 08)."""
    result = classify_dependent(
        _dep(
            birth_date=date(1980, 1, 1),  # 45
            residence=Residence.OVERSEAS,
            country="ブラジル",
        ),
        YEAR,
    )
    assert result.qualifies is False
    assert result.kind == DependentKind.NONE
    assert result.disqualified_reason == "overseas_30_69_no_reason"


def test_overseas_30_69_with_study_qualifies() -> None:
    """国外居住 30-69 con 留学 -> califica, requiere 留学ビザ等書類."""
    result = classify_dependent(
        _dep(
            birth_date=date(1990, 1, 1),  # 35
            residence=Residence.OVERSEAS,
            country="ブラジル",
            overseas_exemption=OverseasExemptionReason.STUDY,
        ),
        YEAR,
    )
    assert result.qualifies is True
    assert result.kind == DependentKind.GENERAL
    assert "ryugaku_visa" in result.required_documents
    assert "shinzoku_kankei" in result.required_documents
    assert "soukin_kankei" in result.required_documents
    assert result.needs_translation is True


def test_elderly_dependent_overseas_separate() -> None:
    """Ejemplo sintético: 70+, 別居, 国外 -> 老人扶養（別居）¥480,000 + checklist docs.

    research 08: vivir en el extranjero NO le quita el 別居老人扶養; solo agrega
    documentos (親族関係 + 送金, sin piso de ¥380k a los 70+).
    """
    result = classify_dependent(
        _dep(
            name="架空 親族",
            relationship="父",
            birth_date=date(1948, 1, 1),  # 77 al 2025
            goukei_shotoku=0,  # sin ingreso de fuente JP
            residence=Residence.OVERSEAS,
            country="ブラジル",
            cohabitation=Cohabitation.SEPARATE,
        ),
        YEAR,
    )
    assert result.kind == DependentKind.ELDERLY
    assert result.income_tax_amount == 480_000
    assert result.resident_tax_amount == 380_000
    assert result.qualifies is True
    assert result.is_overseas is True
    # 70+ no necesita motivo de excepcion (sin piso ¥380k).
    assert result.disqualified_reason is None
    # Documentos: 親族関係 + 送金 (sin 38万 obligatorio a los 70+).
    assert result.required_documents == ["shinzoku_kankei", "soukin_kankei"]
    assert result.needs_translation is True


def test_elderly_dependent_domestic_separate() -> None:
    """Ejemplo sintético de dependiente: 70+, 別居, 国内 (Japón) -> 老人扶養（別居）¥480,000.

    Vive en Japón (国内) y NO conviven (別居) -> 老人扶養親族（別居）¥480,000 所得税 /
    ¥380,000 住民税. Al ser 国内 居住 NO requiere checklist de documentos de 国外
    ni 翻訳文 (esos solo aplican a 国外居住).
    """
    result = classify_dependent(
        _dep(
            name="架空 親族",
            relationship="父",
            birth_date=date(1948, 1, 1),  # 77 al 2025
            goukei_shotoku=0,
            residence=Residence.DOMESTIC,
            cohabitation=Cohabitation.SEPARATE,
        ),
        YEAR,
    )
    assert result.kind == DependentKind.ELDERLY
    assert result.income_tax_amount == 480_000
    assert result.resident_tax_amount == 380_000
    assert result.qualifies is True
    assert result.is_overseas is False
    # 国内 居住: SIN documentos de 国外 ni aviso de 翻訳文.
    assert result.required_documents == []
    assert result.needs_translation is False
    assert result.disqualified_reason is None


def test_deduction_service_structured_dependents() -> None:
    """`deductions_to_input` clasifica dependientes estructurados en meta.dependents.

    Una fila `fuyo` con la lista estructurada de un familiar (70+ 別居 国外 Perú) debe
    aportar ¥480,000 al 扶養控除 del cálculo.
    """
    from app.domain.tax.deduction_service import deductions_to_input
    from app.domain.tax.deductions import dependent_deduction
    from app.models.entities import Deduction
    from app.models.enums import DeductionType

    fila = Deduction(
        type=DeductionType.FUYO,
        amount=480_000,
        meta={
            "year": YEAR,
            "dependents": [
                {
                    "name": "母",
                    "relationship": "母",
                    "birth_date": "1953-05-10",
                    "goukei_shotoku": 0,
                    "residence": "overseas",
                    "country": "ペルー",
                    "cohabitation": "separate",
                }
            ],
        },
    )
    di = deductions_to_input([fila], year=YEAR)
    assert len(di.dependents) == 1
    assert di.dependents[0].kind == DependentKind.ELDERLY
    assert dependent_deduction(di.dependents) == 480_000


def test_deduction_service_overseas_no_reason_not_counted() -> None:
    """Un dependiente 国外 30-69 sin motivo no entra al cálculo (no califica)."""
    from app.domain.tax.deduction_service import deductions_to_input
    from app.models.entities import Deduction
    from app.models.enums import DeductionType

    fila = Deduction(
        type=DeductionType.FUYO,
        amount=0,
        meta={
            "year": YEAR,
            "dependents": [
                {
                    "name": "兄",
                    "birth_date": "1985-01-01",  # 40
                    "goukei_shotoku": 0,
                    "residence": "overseas",
                    "country": "ペルー",
                }
            ],
        },
    )
    di = deductions_to_input([fila], year=YEAR)
    assert di.dependents == []  # 対象外 -> no suma


@pytest.mark.parametrize("metadata_year", [None, 2025, 2026])
def test_deduction_uses_return_year_not_embedded_metadata(metadata_year: int | None) -> None:
    from app.domain.tax.deduction_service import deductions_to_input
    from app.models.entities import Deduction
    from app.models.enums import DeductionType

    meta = {"dependents": [{"name": "母", "birth_date": "1954-04-07",
                            "goukei_shotoku": 600_000, "cohabitation": "separate"}]}
    if metadata_year is not None:
        meta["year"] = metadata_year
    fila = Deduction(type=DeductionType.FUYO, amount=0, meta=meta)
    assert deductions_to_input([fila], year=2025).dependents == []
    assert deductions_to_input([fila], year=2026).dependents[0].kind == DependentKind.ELDERLY


def test_empty_structured_dependents_do_not_fall_back_to_one_person() -> None:
    from app.domain.tax.deduction_service import deductions_to_input
    from app.models.entities import Deduction
    from app.models.enums import DeductionType

    fila = Deduction(type=DeductionType.FUYO, amount=0, meta={"dependents": []})
    assert deductions_to_input([fila], year=2026).dependents == []
