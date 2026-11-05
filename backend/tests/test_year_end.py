"""Generación del borrador oficial de 年末調整 sin persistir datos personales."""

import pymupdf
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.year_end import KisoDraft, YearEndDraft, create_kiso_draft, create_year_end_draft
from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import app
from app.models import Base
from app.models.entities import FiscalYear, Taxpayer
from app.services.forms.kiso_2026 import render_kiso_2026
from app.services.forms.year_end_2026 import render_year_end_2026


def test_year_end_pdf_uses_official_form_and_reviewed_fields() -> None:
    payload = YearEndDraft.model_validate(
        {
            "taxpayer_name": "山田 太郎",
            "taxpayer_kana": "ヤマダ タロウ",
            "employer_name": "株式会社テスト",
            "dependent": {
                "name": "山田 花子",
                "relationship": "母",
                "birth_date": "1954-04-07",
                "income_estimate": 0,
                "elderly_other": True,
            },
            "disability": "ordinary",
            "disability_details": "精神障害者保健福祉手帳 3級",
        },
    )
    response = create_year_end_draft(payload)
    assert response.media_type == "application/pdf"
    assert response.headers["cache-control"] == "no-store"

    doc = pymupdf.open(stream=render_year_end_2026(payload.model_dump()), filetype="pdf")
    assert len(doc) == 2
    text = doc[0].get_text()
    assert "山田 太郎" in text
    assert "山田 花子" in text
    assert "精神障害者保健福祉手帳 3級" in text
    assert "確認用・提出前に確認" in text


def test_year_end_rejects_missing_name_and_invalid_amount() -> None:
    with pytest.raises(ValidationError):
        YearEndDraft.model_validate(
            {"taxpayer_name": "", "dependent": {"name": "X", "income_estimate": -1}}
        )


def test_kiso_draft_fills_only_confirmed_income_and_official_deduction() -> None:
    payload = KisoDraft.model_validate({
        "taxpayer_name": "山田 太郎", "salary_revenue": 5_000_000,
        "other_income": 0, "complete_income_estimate": True,
    })
    assert create_kiso_draft(payload).headers["cache-control"] == "no-store"
    data = render_kiso_2026(payload.model_dump(), 3_560_000)
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        text = doc[0].get_text()
        assert len(doc) == 2
        assert "5000000" in text and "3560000" in text and "1040000" in text
        assert "確認用・提出前に確認" in text
        assert "5000000" in doc[0].get_text(clip=pymupdf.Rect(138, 145, 211, 164))
        assert "3560000" in doc[0].get_text(clip=pymupdf.Rect(221, 145, 304, 164))
        assert "1040000" in doc[0].get_text(clip=pymupdf.Rect(263, 290, 304, 307))

    incomplete = payload.model_copy(update={
        "other_income": None, "complete_income_estimate": False,
    })
    data = render_kiso_2026(incomplete.model_dump(), 3_560_000)
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        assert "1040000" not in doc[0].get_text()


def test_kiso_requires_explicit_complete_income_and_rejects_negative_other() -> None:
    with pytest.raises(ValidationError):
        KisoDraft.model_validate({"taxpayer_name": "山田", "salary_revenue": 5_000_000,
                                  "complete_income_estimate": True})
    with pytest.raises(ValidationError):
        KisoDraft.model_validate({"taxpayer_name": "山田", "other_income": -100})


def test_elderly_category_requires_supporting_birth_date() -> None:
    with pytest.raises(ValidationError):
        YearEndDraft.model_validate(
            {"taxpayer_name": "山田", "dependent": {"name": "花子", "elderly_other": True}}
        )
    with pytest.raises(ValidationError):
        YearEndDraft.model_validate(
            {"taxpayer_name": "山田", "dependent": {
                "name": "花子", "birth_date": "1957-01-02", "elderly_other": True,
            }}
        )
    YearEndDraft.model_validate(
        {"taxpayer_name": "山田", "dependent": {
            "name": "花子", "birth_date": "1957-01-01", "elderly_other": True,
        }}
    )


def test_profile_uses_2026_taxpayer_and_never_returns_my_number() -> None:
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        session.add(Taxpayer(name="Otra persona"))
        taxpayer = Taxpayer(name="山田 太郎", name_kana="ヤマダ タロウ",
                            address="愛知県名古屋市", my_number="123456789012")
        session.add(taxpayer)
        session.flush()
        session.add(FiscalYear(taxpayer_id=taxpayer.id, year=2026, rules_ref="2026.json"))
        session.commit()

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/v1/year-end/2026/profile")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {
            "name": "山田 太郎", "name_kana": "ヤマダ タロウ", "address": "愛知県名古屋市"
        }
        assert "123456789012" not in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_profile_refuses_ambiguous_fallback() -> None:
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        session.add_all([Taxpayer(name="Persona A"), Taxpayer(name="Persona B")])
        session.commit()

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/v1/year-end/2026/profile")
        assert response.status_code == 409
        assert "Persona A" not in response.text
        assert "Persona B" not in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
