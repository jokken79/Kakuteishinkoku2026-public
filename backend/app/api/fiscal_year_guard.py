"""Guard compartido para impedir escrituras en 年度 cerrados o presentados."""

from fastapi import HTTPException, status

from app.models.entities import FiscalYear
from app.models.enums import FiscalYearStatus


def require_open_fiscal_year(fiscal_year: FiscalYear) -> None:
    """Lanza 409 si el 年度 ya no admite cambios contables."""
    current_status = FiscalYearStatus(fiscal_year.status)
    if current_status == FiscalYearStatus.OPEN:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "fiscal_year_locked",
            "message": "締切済み・申告済みの年度は変更できません。再開してから編集してください。",
            "details": {"year": fiscal_year.year, "status": current_status.value},
        },
    )
