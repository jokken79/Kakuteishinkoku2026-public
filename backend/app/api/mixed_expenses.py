"""Simulación sin persistencia de reparto de gastos mixtos."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.domain.mixed_expenses import MixedLine, allocate_mixed_expense

router = APIRouter(tags=["mixed-expenses"])


class LineInput(BaseModel):
    gross: int = Field(ge=0, le=1_000_000_000_000, strict=True)
    tax_rate: int | None = Field(default=None, ge=0, le=100, strict=True)


class AllocationInput(BaseModel):
    original_total: int = Field(ge=0, le=1_000_000_000_000, strict=True)
    numerator: int = Field(ge=0, le=1_000_000_000_000, strict=True)
    denominator: int = Field(gt=0, le=1_000_000_000_000, strict=True)
    lines: list[LineInput] = Field(min_length=1, max_length=100)


@router.post("/mixed-expenses/preview")
def preview_mixed_expense(payload: AllocationInput) -> dict[str, object]:
    """Solo calcula el reparto; no altera el recibo ni crea asientos."""
    try:
        result = allocate_mixed_expense(
            payload.original_total,
            [MixedLine(gross=line.gross, tax_rate=line.tax_rate) for line in payload.lines],
            payload.numerator,
            payload.denominator,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return asdict(result)
