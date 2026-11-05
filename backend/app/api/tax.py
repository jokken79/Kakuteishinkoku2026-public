"""Router de la calculadora fiscal del 所得税.

Expone `POST /tax/calculate` (bajo el prefijo `/api/v1`): recibe un
`TaxCalculationInput` y devuelve el `TaxCalculationResult` con el desglose
completo. La logica es pura y vive en `app.domain.tax`.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.domain.tax import TaxCalculationInput, TaxCalculationResult, calculate
from app.services.tax_rules import load_tax_rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tax", tags=["tax"])


@router.post("/calculate", response_model=TaxCalculationResult)
def calculate_tax(payload: TaxCalculationInput) -> TaxCalculationResult:
    """Calcula el 所得税 a partir de ingresos, deducciones y retenciones.

    Args:
        payload: Entrada completa del calculo (anio, ingresos, deducciones,
            retenciones, 税額控除).

    Returns:
        `TaxCalculationResult` con el desglose (所得, 控除, 課税所得, 所得税,
        復興税, 源泉, 納付額/還付金).

    Raises:
        HTTPException: 400 si no existen parametros fiscales para el anio pedido.
    """
    try:
        rules = load_tax_rules(payload.year)
    except FileNotFoundError as exc:
        logger.warning("Anio fiscal no soportado: %s", payload.year)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unsupported_fiscal_year",
                "message": f"No hay parametros fiscales para el anio {payload.year}.",
                "details": {"year": payload.year},
            },
        ) from exc

    result = calculate(payload, rules)
    logger.info(
        "Calculo 所得税 anio=%s 課税所得=%s 納付額=%s",
        result.year,
        result.taxable_income,
        result.final_amount,
    )
    return result
