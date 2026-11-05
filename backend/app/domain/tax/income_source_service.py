"""Servicio de integracion entre las `IncomeSource` persistidas y el calculo.

Puente entre la capa de persistencia (entidad `IncomeSource`, una fila por
fuente de ingreso real que el owner ingresa: 事業 売上, 給与, 雑所得…) y la
calculadora pura / el motor contable.

Antes el 売上 y el 源泉徴収 vivian HARDCODEADOS en `drafting.py` y `deductions.py`
(¥6,800,000 y ¥410,000). Ahora salen de las `IncomeSource` del 年度: el owner
ingresa SUS ingresos reales y la declaracion sale con sus datos. Si no hay
ninguna `IncomeSource` cargada, los montos son 0 (no el hardcode).

Responsabilidades:
    - `jigyo_sales_revenue`: el 売上 del 事業 (suma de las filas jigyo). Alimenta
      el asiento de 売上 del motor contable (PL).
    - `total_withholding`: Σ源泉徴収税額 de todas las filas (給与 + 報酬 etc.).
    - `extra_income_inputs`: las demas fuentes (給与, 雑, 不動産…) como
      `IncomeInput`, para sumarlas al 事業所得 en el calculo fiscal.

El 事業所得 NO se arma aca: lo deriva el motor contable (売上 − 経費 de los 仕訳 −
青色特別控除). Aca solo se expone el 売上 editable y las fuentes complementarias.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import cast

from app.domain.tax.schemas import IncomeInput, IncomeKind
from app.models.entities import IncomeSource
from app.models.enums import IncomeType

logger = logging.getLogger(__name__)

# `IncomeType` (entidad) -> `IncomeKind` (calculadora). El 事業 no se mapea aca:
# su 所得 lo deriva el motor contable, no la calculadora directa.
_KIND_BY_TYPE: dict[IncomeType, IncomeKind] = {
    IncomeType.KYUYO: IncomeKind.KYUYO,
    IncomeType.ZATSU: IncomeKind.ZATSU,
    IncomeType.FUDOSAN: IncomeKind.FUDOSAN,
    IncomeType.HAITO: IncomeKind.HAITO,
    IncomeType.ICHIJI: IncomeKind.ICHIJI,
}

# Etiquetas en japones para el desglose de 所得 (trazabilidad en el 申告書).
_LABEL_BY_TYPE: dict[IncomeType, str] = {
    IncomeType.KYUYO: "給与所得",
    IncomeType.ZATSU: "雑所得",
    IncomeType.FUDOSAN: "不動産所得",
    IncomeType.HAITO: "配当所得",
    IncomeType.ICHIJI: "一時所得",
}


def _normalize_type(raw: object) -> IncomeType | None:
    """Normaliza el `income_type` (SQLite lo devuelve como str crudo).

    Args:
        raw: Valor de `income_type` (enum o str).

    Returns:
        El `IncomeType` correspondiente o ``None`` si no es valido.
    """
    if isinstance(raw, IncomeType):
        return raw
    try:
        return IncomeType(cast(str, getattr(raw, "value", raw)))
    except ValueError:
        return None


def jigyo_sales_revenue(sources: Iterable[IncomeSource]) -> int:
    """Devuelve el 売上 del 事業 (Σ de las filas jigyo del 年度).

    Es el ingreso bruto del negocio que alimenta el asiento de 売上 del motor
    contable. Si no hay ninguna fila jigyo, devuelve 0 (no el hardcode).

    Args:
        sources: Fuentes de ingreso del 年度.

    Returns:
        売上(収入)金額 del 事業 (>= 0).
    """
    return sum(
        s.gross for s in sources if _normalize_type(s.income_type) == IncomeType.JIGYO
    )


def total_withholding(sources: Iterable[IncomeSource]) -> int:
    """Suma el 源泉徴収税額 de todas las fuentes (給与 + 報酬 etc.).

    Reemplaza el ¥410,000 hardcodeado: el 源泉 sale de lo que el owner ingresa
    desde sus 源泉徴収票 / 支払調書. Si no hay fuentes, devuelve 0.

    Args:
        sources: Fuentes de ingreso del 年度.

    Returns:
        Σ源泉徴収税額 (>= 0).
    """
    return sum(s.withholding for s in sources)


def extra_income_inputs(sources: Iterable[IncomeSource]) -> list[IncomeInput]:
    """Convierte las fuentes NO-jigyo en `IncomeInput` para el calculo fiscal.

    El 事業所得 se deriva del motor contable (no de la calculadora), por eso las
    filas jigyo se excluyen aca. El resto (給与/雑/不動産/配当/一時) se suma al
    合計所得金額 via `calculate()`.

    Para 給与 (KYUYO) se usa `revenue` (収入金額; la calculadora resta el
    給与所得控除). Para 雑/不動産/一時 se usan `revenue` y `expenses`. Para 配当 se
    usa `amount` (ya neto).

    Args:
        sources: Fuentes de ingreso del 年度.

    Returns:
        Lista de `IncomeInput` de las fuentes complementarias (sin jigyo).
    """
    inputs: list[IncomeInput] = []
    for source in sources:
        income_type = _normalize_type(source.income_type)
        if income_type is None or income_type == IncomeType.JIGYO:
            continue
        kind = _KIND_BY_TYPE.get(income_type)
        if kind is None:
            logger.warning("IncomeType sin mapeo a la calculadora: %s", income_type)
            continue
        label = _LABEL_BY_TYPE.get(income_type)
        meta = source.meta or {}
        expenses = int(cast(int, meta.get("expenses", 0)))
        if kind in (IncomeKind.HAITO,):
            inputs.append(IncomeInput(kind=kind, amount=source.gross, label=label))
        else:
            inputs.append(
                IncomeInput(
                    kind=kind,
                    revenue=source.gross,
                    expenses=expenses,
                    label=label,
                )
            )
    return inputs
