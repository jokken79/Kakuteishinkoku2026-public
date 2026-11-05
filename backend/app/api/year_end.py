"""Generación provisional de 扶養控除等申告書 2026 a partir de datos revisados."""

from __future__ import annotations

import io
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.tax.income import salary_income
from app.models.entities import FiscalYear, Taxpayer
from app.services.forms.kiso_2026 import render_kiso_2026
from app.services.forms.year_end_2026 import render_year_end_2026
from app.services.tax_rules import load_tax_rules

router = APIRouter(prefix="/year-end", tags=["year-end"])


class YearEndProfile(BaseModel):
    name: str
    name_kana: str | None
    address: str | None


@router.get("/2026/profile", response_model=YearEndProfile)
def year_end_profile(response: Response, db: Session = Depends(get_db)) -> YearEndProfile:
    """Lee únicamente los datos del perfil necesarios para el borrador."""
    fiscal_years = db.scalars(select(FiscalYear).where(FiscalYear.year == 2026).limit(2)).all()
    if len(fiscal_years) > 1:
        raise HTTPException(status_code=409, detail="Hay más de un perfil asociado a 2026.")
    taxpayer: Taxpayer | None
    if fiscal_years:
        taxpayer = fiscal_years[0].taxpayer
    else:
        taxpayers = db.scalars(select(Taxpayer).limit(2)).all()
        if len(taxpayers) > 1:
            raise HTTPException(
                status_code=409, detail="No se puede elegir un perfil sin ambigüedad."
            )
        taxpayer = taxpayers[0] if taxpayers else None
    if taxpayer is None:
        raise HTTPException(status_code=404, detail="No hay perfil registrado.")
    response.headers["Cache-Control"] = "no-store"
    return YearEndProfile(
        name=taxpayer.name, name_kana=taxpayer.name_kana, address=taxpayer.address
    )


class YearEndDependent(BaseModel):
    name: str = Field(min_length=1, max_length=35)
    name_kana: str = Field(default="", max_length=35)
    relationship: str = Field(default="", max_length=8)
    birth_date: date | None = None
    address: str = Field(default="", max_length=51)
    income_estimate: int | None = Field(default=None, ge=0, le=999_999_999)
    elderly_other: bool = False

    @model_validator(mode="after")
    def validate_elderly_category(self) -> YearEndDependent:
        """La categoría requiere edad comprobable; no determina otros requisitos."""
        if self.elderly_other and (self.birth_date is None or self.birth_date > date(1957, 1, 1)):
            raise ValueError("老人扶養親族には生年月日の確認が必要です。")
        return self


class YearEndDraft(BaseModel):
    taxpayer_name: str = Field(min_length=1, max_length=35)
    taxpayer_kana: str = Field(default="", max_length=35)
    taxpayer_address: str = Field(default="", max_length=65)
    employer_name: str = Field(default="", max_length=45)
    dependent: YearEndDependent | None = None
    disability: Literal["none", "ordinary"] = "none"
    disability_details: str = Field(default="", max_length=75)


class KisoDraft(BaseModel):
    taxpayer_name: str = Field(min_length=1, max_length=35)
    taxpayer_kana: str = Field(default="", max_length=35)
    taxpayer_address: str = Field(default="", max_length=65)
    employer_name: str = Field(default="", max_length=45)
    salary_revenue: int | None = Field(default=None, ge=0, le=8_500_000, strict=True)
    other_income: int | None = Field(default=None, ge=0, le=25_000_000, strict=True)
    complete_income_estimate: bool = False

    @model_validator(mode="after")
    def validate_complete_estimate(self) -> KisoDraft:
        if self.complete_income_estimate and (
            self.salary_revenue is None or self.other_income is None
        ):
            raise ValueError("給与収入と給与以外の所得の見積額が必要です。")
        return self


@router.post("/2026/kiso-draft", response_class=StreamingResponse)
def create_kiso_draft(payload: KisoDraft) -> StreamingResponse:
    """Prepara solo campos revisables; no presenta ni persiste datos."""
    salary = (
        salary_income(payload.salary_revenue, load_tax_rules(2026))
        if payload.salary_revenue is not None else None
    )
    content = render_kiso_2026(payload.model_dump(), salary)
    return StreamingResponse(
        io.BytesIO(content), media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="kiso_2026_review.pdf"',
                 "Cache-Control": "no-store"},
    )


@router.post("/2026/fuyo-draft", response_class=StreamingResponse)
def create_year_end_draft(payload: YearEndDraft) -> StreamingResponse:
    """Devuelve PDF de revisión; no almacena ni presenta los datos."""
    content = render_year_end_2026(payload.model_dump())
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="fuyo_2026_review.pdf"',
            "Cache-Control": "no-store",
        },
    )
