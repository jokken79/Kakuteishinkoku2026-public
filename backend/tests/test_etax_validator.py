"""Tests del validador estructural del .xtx (``etax_validator``).

Casos crafteados (rápidos, sin DB) para cada regla + un caso de integración que
valida el .xtx real generado por ``build_xtx`` desde el seed.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import create_db_engine, get_session_factory
from app.models import Base
from app.models.entities import Transaction
from app.models.enums import TransactionStatus
from app.seed.dev_seed import seed_demo_data
from app.services.forms.drafting import build_filing_draft
from app.services.forms.etax_export import build_xtx
from app.services.forms.etax_validator import load_valid_tags, validate_xtx

_PROLOG = '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>'


def _wrap(body: str, *, prolog: str = _PROLOG, vr: str = "23.0") -> bytes:
    """Arma un .xtx mínimo con cabecera 年分 válida + ``body`` extra."""
    xml = (
        f"{prolog}\n"
        f'<DATA>\n  <KOA020 VR="{vr}" id="KOA020">\n    <KOA020-1>\n'
        "      <ABA00000>\n"
        "        <ABA00010><Gengo>5</Gengo><Nen>07</Nen></ABA00010>\n"
        "        <ABA00140>架空 花子</ABA00140>\n"
        "      </ABA00000>\n"
        f"      <ABB00000>\n{body}\n      </ABB00000>\n"
        "    </KOA020-1>\n  </KOA020>\n</DATA>\n"
    )
    return xml.encode("utf-8")


def _codes(data: bytes, *, year: int = 2025) -> list[str]:
    return [i.code for i in validate_xtx(data, year=year).issues]


# --- Esquema -----------------------------------------------------------------


def test_load_valid_tags_has_confirmed_set() -> None:
    """El esquema confirmado trae los tags ABA/ABB clave."""
    tags = load_valid_tags()
    assert "ABB00410" in tags  # 合計所得金額.
    assert "ABA00010" in tags  # 年分.
    assert "ABB00550" in tags  # 基礎控除.
    assert len(tags) >= 100


# --- Caso válido -------------------------------------------------------------


def test_legacy_diagnostic_never_confirms_submission_readiness() -> None:
    data = _wrap("        <ABB00410>5818502</ABB00410>")
    report = validate_xtx(data, year=2025)
    assert not report.ok
    assert "official_xsd_not_validated" in [i.code for i in report.issues]
    assert "ABB00410" in report.emitted_field_tags


# --- Estructura --------------------------------------------------------------


def test_bad_prolog_is_error() -> None:
    data = _wrap("        <ABB00410>1</ABB00410>", prolog='<?xml version="1.0" ?>')
    assert "prolog" in _codes(data)


def test_not_well_formed_is_error() -> None:
    data = (_PROLOG + "\n<DATA><KOA020></DATA>").encode("utf-8")
    assert "not_well_formed" in _codes(data)


def test_wrong_root_is_error() -> None:
    data = (_PROLOG + "\n<ROOT></ROOT>").encode("utf-8")
    assert "root" in _codes(data)


def test_missing_form_is_error() -> None:
    data = (_PROLOG + "\n<DATA></DATA>").encode("utf-8")
    assert "missing_form" in _codes(data)


def test_vr_mismatch_is_warning() -> None:
    data = _wrap("        <ABB00410>1</ABB00410>", vr="22.0")
    report = validate_xtx(data, year=2025)
    assert not report.ok  # falta validación XSD oficial
    assert "vr_mismatch" in [i.code for i in report.issues]


# --- Reglas de campo ---------------------------------------------------------


def test_unknown_tag_is_error() -> None:
    data = _wrap("        <ABB99999>1</ABB99999>")
    assert "unknown_tag" in _codes(data)


def test_amount_with_separators_is_error() -> None:
    data = _wrap("        <ABB00410>5,818,502</ABB00410>")
    assert "amount_separator" in _codes(data)


def test_rounding_violation_is_warning() -> None:
    # 課税所得 (ABB00580) debe ser múltiplo de 1000.
    data = _wrap("        <ABB00580>4612345</ABB00580>")
    report = validate_xtx(data, year=2025)
    assert not report.ok  # falta validación XSD oficial
    assert "rounding" in [i.code for i in report.issues]


def test_koa210_is_not_declared_retired() -> None:
    body = (
        "        <ABB00410>1</ABB00410>\n"
        "      </ABB00000>\n"
        "      <KOA210></KOA210>\n"
        "      <ABB00000>"
    )
    data = _wrap(body)
    assert "retired_form" not in _codes(data)


# --- 年分 --------------------------------------------------------------------


def test_wrong_era_for_reiwa_year_is_warning() -> None:
    body = "        <ABB00410>1</ABB00410>"
    xml = _wrap(body).replace(b"<Gengo>5</Gengo>", b"<Gengo>4</Gengo>")
    assert "era_year" in _codes(xml)


# --- Integración: .xtx real --------------------------------------------------


def test_generated_xtx_is_not_certified_by_legacy_diagnostic() -> None:
    """El generador heredado nunca se certifica con el diagnóstico interno."""
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    session: Session = get_session_factory(engine)()
    seed_demo_data(session)
    for tx in session.query(Transaction).all():
        tx.status = TransactionStatus.CONFIRMED
    session.commit()
    try:
        draft = build_filing_draft(session, year=2025)
        report = validate_xtx(build_xtx(draft), year=2025)
        assert not report.ok
        assert "official_xsd_not_validated" in [i.code for i in report.issues]
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
