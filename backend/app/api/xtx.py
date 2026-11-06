"""Revisión transitoria del XTX: sin persistir ni devolver identificadores."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.filing import _draft_or_404, _require_verified_export
from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import FiscalYear
from app.services.forms.drafting import FilingDraftResult, build_filing_draft
from app.services.forms.etax_validator import validate_xtx_against_xsd
from app.services.forms.tax_office import resolve_tax_office
from app.services.forms.xtx_document import (
    MunicipalDonation,
    PayerIncome,
    PremiumPayment,
    XtxDetails,
    build_xtx_document,
)
from app.services.forms.xtx_envelope import XtxIdentity
from app.services.forms.xtx_insurance import InsuranceCategory, InsurancePayment

Money = Annotated[int, Field(strict=True, ge=0, le=999_999_999_999)]
Text = Annotated[str, Field(min_length=1, max_length=100, pattern=r".*\S.*")]


class PrivateXtxRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def private(request: Request) -> Response:
            try:
                response = await original(request)
            except RequestValidationError:
                # FastAPI incluye el input original en 422: nunca devolverlo para identidad.
                response = JSONResponse(status_code=422, content={"detail": {
                    "code": "xtx_input_invalid",
                    "message": "Revisa los campos: dígitos ASCII, fechas e importes enteros.",
                }})
            except HTTPException as exc:
                response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            return response

        return private


router = APIRouter(prefix="/filing", tags=["filing"], route_class=PrivateXtxRoute)


class PrivateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class IdentityInput(PrivateInput):
    user_id: str = Field(pattern=r"^[0-9]{16}$", repr=False)
    my_number: str | None = Field(default=None, pattern=r"^[0-9]{12}$", repr=False)
    birth_date: date | None = Field(default=None, repr=False)


class PayerInput(PrivateInput):
    kind: Literal["jigyo", "kyuyo"]
    name: Text = Field(repr=False)
    location: Text = Field(repr=False)
    gross: Money
    withholding: Money


class PremiumInput(PrivateInput):
    category: Literal["social", "ideco"]
    label: Text
    paid: Money
    outside_year_end_adjustment: Money


class InsuranceInput(PrivateInput):
    category: InsuranceCategory
    paid: Money
    outside_year_end_adjustment: Money


class DonationInput(PrivateInput):
    name: Text = Field(repr=False)
    location: Text = Field(repr=False)
    paid: Annotated[int, Field(strict=True, gt=0, le=999_999_999_999)]


class DetailsInput(PrivateInput):
    payers: list[PayerInput] = Field(default_factory=list, max_length=40, repr=False)
    premiums: list[PremiumInput] = Field(default_factory=list, max_length=6)
    insurance: list[InsuranceInput] = Field(default_factory=list, max_length=40)
    separate_damage_contracts: bool = False
    donations: list[DonationInput] = Field(default_factory=list, max_length=40, repr=False)
    monthly_sales: tuple[Money, ...] | None = Field(default=None, min_length=12, max_length=12)
    opening_balances: dict[Text, Money] | None = Field(default=None, max_length=30, repr=False)
    business_period: tuple[date, date] | None = None

    def domain(self) -> XtxDetails:
        return XtxDetails(
            payers=tuple(PayerIncome(**row.model_dump()) for row in self.payers),
            premiums=tuple(PremiumPayment(**row.model_dump()) for row in self.premiums),
            insurance=tuple(InsurancePayment(**row.model_dump()) for row in self.insurance),
            separate_damage_contracts=self.separate_damage_contracts,
            donations=tuple(MunicipalDonation(**row.model_dump()) for row in self.donations),
            monthly_sales=self.monthly_sales,
            opening_balances=self.opening_balances,
            business_period=self.business_period,
        )


class XtxRequest(PrivateInput):
    identity: IdentityInput = Field(repr=False)
    details: DetailsInput = Field(default_factory=DetailsInput, repr=False)


class XtxReview(BaseModel):
    year: int
    schema_valid: bool | None
    ready_for_submission: bool
    missing: list[str]


def _preview(db: Session, draft_id: uuid.UUID) -> FilingDraftResult:
    stored = _draft_or_404(db, draft_id)
    fiscal = db.get(FiscalYear, stored.fiscal_year_id)
    if fiscal is None:
        raise HTTPException(404, detail={"code": "no_fiscal_year"})
    _require_verified_export(fiscal.year)
    return build_filing_draft(db, fiscal.year, persist=False, preview_projection=True)


@router.get("/{draft_id}/xtx/context")
def context(draft_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = _preview(db, draft_id)
    profile = result.taxpayer_profile
    if profile is None:
        raise HTTPException(409, detail={"code": "taxpayer_profile_missing"})
    return {
        "year": result.year, "name": result.taxpayer_name, "address": profile.address,
        "office_code": resolve_tax_office(profile.filing_office_key).etax_code,
        "name_kana": profile.name_kana, "postal_code": profile.postal_code,
        "occupation": profile.occupation,
        "sales_revenue": result.sales_revenue, "salary_revenue": result.salary_revenue,
        "withholding": result.tax.withholding_tax,
        "social_insurance": result.tax.deduction_breakdown.social_insurance,
        "ideco": result.tax.deduction_breakdown.ideco,
        "life_insurance": result.tax.deduction_breakdown.life_insurance,
        "earthquake_insurance": result.tax.deduction_breakdown.earthquake_insurance,
    }


def _review(result: FilingDraftResult, payload: XtxRequest) -> tuple[XtxReview, bytes]:
    profile = result.taxpayer_profile
    if profile is None or not profile.address:
        raise HTTPException(409, detail={"code": "taxpayer_profile_missing",
                                        "message": "Completa el nombre y dirección en el perfil."})
    office = resolve_tax_office(profile.filing_office_key).etax_code
    if not office:
        return XtxReview(year=result.year, schema_valid=None, ready_for_submission=False,
                         missing=["tax_office_assignment"]), b""
    identity = XtxIdentity(
        payload.identity.user_id, result.taxpayer_name, profile.address, office,
        payload.identity.my_number, payload.identity.birth_date,
    )
    try:
        document = build_xtx_document(
            result, identity, created_on=datetime.now(ZoneInfo("Asia/Tokyo")).date(),
            details=payload.details.domain(),
        )
    except ValueError:
        # Excepciones del dominio pueden contener nombres de cuentas ingresados.
        return XtxReview(year=result.year, schema_valid=None, ready_for_submission=False,
                         missing=["details_incompatible"]), b""
    missing = list(document.missing)
    missing.extend("filing_checklist:" + item.key for item in result.checklist if not item.done)
    schema_valid = None
    schema_path = get_settings().etax_official_xsd
    if not schema_path:
        missing.append("xsd_missing")
    else:
        report = validate_xtx_against_xsd(document.xml, Path(schema_path), year=result.year)
        schema_valid = report.ok
        missing.extend(issue.code for issue in report.issues if issue.level == "error")
    missing = sorted(set(missing))
    return XtxReview(
        year=result.year, schema_valid=schema_valid,
        ready_for_submission=document.ready_for_submission and schema_valid is True and not missing,
        missing=missing,
    ), document.xml


@router.post("/{draft_id}/xtx/review", response_model=XtxReview)
def review(draft_id: uuid.UUID, payload: XtxRequest, db: Session = Depends(get_db)) -> XtxReview:
    report, _ = _review(_preview(db, draft_id), payload)
    return report


@router.post("/{draft_id}/xtx")
def download(draft_id: uuid.UUID, payload: XtxRequest, db: Session = Depends(get_db)) -> Response:
    # Recalcular y validar de nuevo: nunca confiar en un permiso enviado por el navegador.
    report, content = _review(_preview(db, draft_id), payload)
    if not report.ready_for_submission:
        raise HTTPException(409, detail={
            "code": "xtx_not_ready",
            "message": "La declaración aún no está lista para presentar.",
            "missing": report.missing,
        })
    return Response(content, media_type="application/xml", headers={
        "Content-Disposition": f'attachment; filename="shinkoku_{report.year}.xtx"',
    })
