"""Motor de calculo del 消費税 (impuesto al consumo) — Fase 消費税.

Calcula el 消費税及び地方消費税 de un 課税事業者 (個人事業主) por los tres
metodos como escenarios orientativos, sin verificar aún su elegibilidad:

    - **本則課税**  : 売上税額 − 仕入税額控除 real (消費税 de los 仕訳/gastos con
                      適格請求書), con 区分経理 8% / 10%.
    - **簡易課税**  : 売上税額 × みなし仕入率 segun 事業区分 (第1〜6種).
    - **2割特例**   : 売上税額 × 20% (ejercicio anual individual hasta 2026).
      Para 2027 y 2028 existe el 3割特例, sujeto a requisitos adicionales.

納付税額 = 売上税額 − 仕入税額控除 (国税分) ; el 地方消費税 se deriva del 国税分
(税率 7.8% nacional + 2.2% local dentro del 10%; 6.24% + 1.76% dentro del 8%).

Regla de arquitectura: tasas / みなし仕入率 / fechas del 特例 son **configuracion
parametrizada por anio fiscal** (`consumption` en `app/tax_rules/{year}.json`),
nunca hardcode (research 01 §0, §6).

⚠️ Alcance honesto (MVP):
    - El 売上 viene del 売上(収入)金額 del 事業 (IncomeSource jigyo), tratado como
      税込 (割戻し計算: 国税分 = 税込 × 7.8/110 o 6.24/108). Se permite indicar que
      parte es 8% via `reduced_ratio` (default 0 = todo 10%).
    - El 基準期間 (前々年 > ¥10M) NO se evalua automaticamente: el owner se marca
      課税事業者 explicitamente (`is_taxable_consumption`).
    - El 仕入税額控除 本則 usa el 割戻し計算 (no el 積上げ計算) sobre los 税込 de los
      gastos confirmados con `is_qualified_invoice=True`.
"""

from __future__ import annotations

import logging
from datetime import date
from enum import StrEnum
from typing import Literal, cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.mixed_expenses import transaction_allocation
from app.models.entities import FiscalYear, IncomeSource, Transaction
from app.models.enums import (
    IncomeType,
    TransactionStatus,
)
from app.services.tax_rules import ConsumptionRules, TaxRules, load_tax_rules

logger = logging.getLogger(__name__)


class ConsumptionMethodKey(StrEnum):
    """Clave de un metodo de calculo del 消費税 (para el comparador)."""

    HONSOKU = "honsoku"  # 本則課税
    KANI = "kani"  # 簡易課税
    TOKUREI = "tokurei"  # 2割特例 / 3割特例 (segun fecha)


# 事業区分 (1〜6) -> clave de la みなし仕入率 en el JSON (`deemed_purchase_rates`).
# 第1種 卸売 90% / 第2種 小売 80% / 第3種 製造 70% / 第4種 その他 60% /
# 第5種 サービス 50% / 第6種 不動産 40%.
BUSINESS_CATEGORY_LABELS: dict[int, str] = {
    1: "第1種（卸売業）",
    2: "第2種（小売業）",
    3: "第3種（製造業等）",
    4: "第4種（その他）",
    5: "第5種（サービス業等）",
    6: "第6種（不動産業）",
}


class SalesTaxBreakdown(BaseModel):
    """Desglose del 売上税額 (区分経理 por tasa).

    Args:
        taxable_sales_8: 課税売上 (税込) gravado al 軽減8%.
        taxable_sales_10: 課税売上 (税込) gravado al 標準10%.
        national_tax_8: 消費税(国税分) del 8% (税込 × 6.24/108).
        national_tax_10: 消費税(国税分) del 10% (税込 × 7.8/110).
        national_tax_total: 売上に係る消費税額 (国税分) total (8% + 10%).
    """

    taxable_sales_8: int
    taxable_sales_10: int
    national_tax_8: int
    national_tax_10: int
    national_tax_total: int


class PurchaseTaxBreakdown(BaseModel):
    """Desglose del 仕入税額控除 本則 (区分経理 por tasa).

    Solo cuenta los gastos confirmados con 適格請求書 (`is_qualified_invoice`).

    Args:
        qualified_purchases_8: 課税仕入 (税込) al 8% con 適格請求書.
        qualified_purchases_10: 課税仕入 (税込) al 10% con 適格請求書.
        national_tax_8: 仕入に係る消費税(国税分) del 8% (税込 × 6.24/108).
        national_tax_10: 仕入に係る消費税(国税分) del 10% (税込 × 7.8/110).
        national_tax_total: 控除対象仕入税額 (国税分) total.
        excluded_non_qualified: Σ 税込 de gastos SIN 適格請求書 (no deducibles).
    """

    qualified_purchases_8: int
    qualified_purchases_10: int
    national_tax_8: int
    national_tax_10: int
    national_tax_total: int
    excluded_non_qualified: int


class ConsumptionOption(BaseModel):
    """Resultado de un metodo de calculo del 消費税.

    Todos los montos son 国税分 salvo `local_tax` y los `*_total`.

    Args:
        method: Clave del metodo (honsoku / kani / tokurei).
        label: Etiqueta japonesa del metodo (本則課税 / 簡易課税 / 2割特例).
        eligible: ``True`` solo si la elegibilidad está verificada. Por ahora
            siempre es ``False``; consultar también ``eligibility_status``.
        eligibility_status: ``unverified`` si faltan datos o ``unavailable``
            si el escenario no está disponible según los datos conocidos.
        sales_tax: 売上に係る消費税額 (国税分).
        purchase_tax_credit: 仕入税額控除 (国税分) aplicado por el metodo.
        national_tax: 消費税(国税分) = 売上税額 − 仕入税額控除 (>= 0).
        local_tax: 地方消費税額 (= 国税分 × 22/78, redondeado).
        total_tax: 納付税額 = 国税分 + 地方消費税分 (lo que se ingresa).
        note: Detalle del metodo (みなし仕入率, tasa del 特例, etc.).
    """

    method: ConsumptionMethodKey
    label: str
    eligible: bool
    eligibility_status: Literal["unverified", "unavailable"] = "unverified"
    sales_tax: int
    purchase_tax_credit: int
    national_tax: int
    local_tax: int
    total_tax: int
    note: str | None = None


class ConsumptionResult(BaseModel):
    """Resultado completo del calculo del 消費税 (las 3 opciones + sugerencia).

    Args:
        year: 年度.
        is_taxable: ``True`` si el contribuyente es 課税事業者.
        method_setting: Metodo elegido en la config del Taxpayer (informativo).
        business_category: 事業区分 (1〜6) para 簡易課税, o ``None``.
        sales_breakdown: Desglose del 売上税額 (8% / 10%).
        purchase_breakdown: Desglose del 仕入税額控除 本則 (8% / 10%).
        honsoku: Escenario 本則課税.
        kani: Escenario 簡易課税 (necesita 事業区分 para simular).
        tokurei: Escenario 2割特例 / 3割特例.
        recommended: Siempre ``None`` mientras no se verifique la elegibilidad.
        recommended_saving: Siempre 0 mientras no exista recomendación.
        as_of: Fecha usada para resolver 2割特例 vs 3割特例 (parametrizacion).
    """

    year: int
    is_taxable: bool
    method_setting: str | None
    business_category: int | None
    sales_breakdown: SalesTaxBreakdown
    purchase_breakdown: PurchaseTaxBreakdown
    honsoku: ConsumptionOption
    kani: ConsumptionOption
    tokurei: ConsumptionOption
    recommended: ConsumptionMethodKey | None
    recommended_saving: int
    as_of: date


# --- Helpers de calculo (割戻し計算) ---------------------------------------


def _national_tax_from_taxed(amount_incl: int, rate: int, rules: ConsumptionRules) -> int:
    """消費税(国税分) de un importe 税込 por 割戻し計算 (truncado).

    国税分 = 税込 × (national_rate / (100 + rate)). Para 10%: 7.8/110; para 8%:
    6.24/108. Se trunca a entero (国税庁: 端数切捨て del 課税標準額×税率).

    Args:
        amount_incl: Importe 税込 (con 消費税 incluido).
        rate: Tasa total aplicada (8 o 10).
        rules: Parametros del 消費税 del anio.

    Returns:
        消費税(国税分) truncado a entero (>= 0).
    """
    if amount_incl <= 0:
        return 0
    national_rate = rules.national_rate_for(rate)
    return int(amount_incl * national_rate / (100 + rate))


def _local_from_national(national_tax: int, rules: ConsumptionRules) -> int:
    """地方消費税額 a partir del 国税分 (= 国税分 × 22/78, truncado).

    El 地方消費税 es el 22/78 del 消費税(国税分) (research 06): dentro del 10% el
    7.8% es nacional y el 2.2% local; 2.2/7.8 = 22/78.

    Args:
        national_tax: 消費税(国税分) ya neto.
        rules: Parametros del 消費税 del anio.

    Returns:
        地方消費税額 truncado a entero (>= 0).
    """
    if national_tax <= 0:
        return 0
    return int(national_tax * rules.local_tax_ratio_num / rules.local_tax_ratio_den)


def _round_down_100(amount: int) -> int:
    """Redondea a la baja al centenar (¥100未満切り捨て) del 納付税額.

    El 国税庁 redondea el 納付税額 final a ¥100 (100円未満切り捨て).

    Args:
        amount: Importe a redondear (>= 0).

    Returns:
        Importe redondeado a la baja a ¥100.
    """
    if amount <= 0:
        return 0
    return (amount // 100) * 100


# --- Construccion de los desgloses (売上 / 仕入) ----------------------------


def _split_sales(gross: int, reduced_ratio: float) -> tuple[int, int]:
    """Separa el 売上 (税込) en parte 8% (軽減) y 10% (標準) segun `reduced_ratio`.

    Args:
        gross: 売上(収入)金額 税込 total del 事業.
        reduced_ratio: Proporcion (0.0-1.0) del 売上 gravado al 軽減8%.

    Returns:
        Tupla ``(sales_8, sales_10)`` (税込 de cada tasa).
    """
    ratio = min(1.0, max(0.0, reduced_ratio))
    sales_8 = int(round(gross * ratio))
    sales_10 = gross - sales_8
    return sales_8, sales_10


def _sales_breakdown(
    sources: list[IncomeSource], rules: ConsumptionRules
) -> SalesTaxBreakdown:
    """Arma el 売上税額 (区分経理 8/10%) desde las filas jigyo.

    El 売上 es el Σ gross de las filas jigyo (税込). La proporcion 軽減8% se lee
    de `meta.consumption.reduced_ratio` (default 0 = todo 10%).

    Args:
        sources: Fuentes de ingreso del 年度.
        rules: Parametros del 消費税 del anio.

    Returns:
        `SalesTaxBreakdown` con el 売上税額 (国税分) por tasa.
    """
    sales_8 = 0
    sales_10 = 0
    for s in sources:
        raw_type = getattr(s.income_type, "value", s.income_type)
        if raw_type != IncomeType.JIGYO.value:
            continue
        meta = s.meta or {}
        cons_meta = meta.get("consumption") if isinstance(meta, dict) else None
        reduced_ratio = 0.0
        if isinstance(cons_meta, dict):
            reduced_ratio = float(cons_meta.get("reduced_ratio", 0.0) or 0.0)
        part_8, part_10 = _split_sales(s.gross, reduced_ratio)
        sales_8 += part_8
        sales_10 += part_10

    tax_8 = _national_tax_from_taxed(sales_8, 8, rules)
    tax_10 = _national_tax_from_taxed(sales_10, 10, rules)
    return SalesTaxBreakdown(
        taxable_sales_8=sales_8,
        taxable_sales_10=sales_10,
        national_tax_8=tax_8,
        national_tax_10=tax_10,
        national_tax_total=tax_8 + tax_10,
    )


def _purchase_breakdown(
    confirmed: list[Transaction], rules: ConsumptionRules
) -> PurchaseTaxBreakdown:
    """Arma el 仕入税額控除 本則 (区分経理 8/10%) desde los gastos confirmados.

    Solo cuentan los 取引 confirmados con `is_qualified_invoice=True` (インボイス
    制度: sin 適格請求書 no hay 仕入税額控除). El 税込 y la tasa salen de
    `tax_lines` (区分経理); si no hay `tax_lines`, se asume 10% sobre el total.

    Args:
        confirmed: Transacciones confirmadas del 年度 (gastos).
        rules: Parametros del 消費税 del anio.

    Returns:
        `PurchaseTaxBreakdown` con el 控除対象仕入税額 (国税分) por tasa.
    """
    purch_8 = 0
    purch_10 = 0
    excluded = 0
    for tx in confirmed:
        allocation = transaction_allocation(tx)
        total = allocation.business_total if allocation is not None else tx.total_amount or 0
        if total <= 0:
            continue
        if not tx.is_qualified_invoice:
            excluded += total
            continue
        if allocation is not None:
            for allocated_line in allocation.lines:
                if allocated_line.original.tax_rate == 8:
                    purch_8 += allocated_line.business
                elif allocated_line.original.tax_rate != 0:
                    purch_10 += allocated_line.business
            continue
        lines = tx.tax_lines or []
        if not lines:
            # Sin desglose: asumir 10% sobre el total 税込.
            purch_10 += total
            continue
        for line in lines:
            rate = int(cast(int, line.get("rate", 10) or 10))
            base = line.get("base")
            tax = line.get("tax")
            # 税込 de la linea: base + tax si vienen; si no, el total.
            if base is not None and tax is not None:
                incl = int(cast(int, base)) + int(cast(int, tax))
            else:
                incl = total
            if rate == 8:
                purch_8 += incl
            else:
                purch_10 += incl

    tax_8 = _national_tax_from_taxed(purch_8, 8, rules)
    tax_10 = _national_tax_from_taxed(purch_10, 10, rules)
    return PurchaseTaxBreakdown(
        qualified_purchases_8=purch_8,
        qualified_purchases_10=purch_10,
        national_tax_8=tax_8,
        national_tax_10=tax_10,
        national_tax_total=tax_8 + tax_10,
        excluded_non_qualified=excluded,
    )


# --- Construccion de cada opcion -------------------------------------------


def _make_option(
    method: ConsumptionMethodKey,
    label: str,
    *,
    eligible: bool,
    eligibility_status: Literal["unverified", "unavailable"],
    sales_tax: int,
    purchase_tax_credit: int,
    rules: ConsumptionRules,
    note: str | None = None,
) -> ConsumptionOption:
    """Construye una `ConsumptionOption` con el 納付税額 (国税 + 地方) redondeado.

    納付税額(国税分) = max(0, 売上税額 − 仕入税額控除), redondeado a ¥100; el
    地方消費税 se deriva del 国税分 neto. El total es lo que se ingresa.

    Args:
        method: Clave del metodo.
        label: Etiqueta japonesa.
        eligible: Si el metodo es elegible.
        sales_tax: 売上税額 (国税分).
        purchase_tax_credit: 仕入税額控除 (国税分) del metodo.
        rules: Parametros del 消費税 del anio.
        note: Detalle del metodo.

    Returns:
        La `ConsumptionOption` completa.
    """
    national = max(0, sales_tax - purchase_tax_credit)
    national_rounded = _round_down_100(national)
    local = _round_down_100(_local_from_national(national_rounded, rules))
    return ConsumptionOption(
        method=method,
        label=label,
        eligible=eligible,
        eligibility_status=eligibility_status,
        sales_tax=sales_tax,
        purchase_tax_credit=purchase_tax_credit,
        national_tax=national_rounded,
        local_tax=local,
        total_tax=national_rounded + local,
        note=note,
    )


def _tokurei_rate(as_of: date, rules: ConsumptionRules) -> tuple[float, str]:
    """Resuelve la tasa para el ejercicio anual de un contribuyente individual.

    El 2割特例 cubre el periodo que contiene el 30/09/2026, es decir todo el
    ejercicio anual 2026. El 3割特例 cubre 2027 y 2028, no octubre de 2026.
    Los periodos abreviados y la elegibilidad individual requieren más datos.

    Args:
        as_of: Fecha de referencia (tipicamente el cierre del 年度).
        rules: Parametros del 消費税 del anio.

    Returns:
        Tupla ``(rate, label)`` con la tasa (0.20 / 0.30) y la etiqueta.
    """
    if rules.tokurei_2wari_until is None or rules.year <= rules.tokurei_2wari_until.year:
        return rules.tokurei_2wari_rate, "2割特例"
    return rules.tokurei_3wari_rate, "3割特例"


def calculate_consumption_tax(
    *,
    sources: list[IncomeSource],
    confirmed: list[Transaction],
    is_taxable: bool,
    method_setting: str | None,
    business_category: int | None,
    is_individual: bool,
    rules: ConsumptionRules,
    as_of: date,
) -> ConsumptionResult:
    """Calcula escenarios de 消費税 sin recomendar métodos no verificados.

    Args:
        sources: Fuentes de ingreso del 年度 (el 売上 sale de las filas jigyo).
        confirmed: Transacciones confirmadas (gastos) para el 仕入税額控除 本則.
        is_taxable: ``True`` si el contribuyente es 課税事業者.
        method_setting: Metodo elegido en la config (informativo).
        business_category: 事業区分 (1〜6) para 簡易課税 (None si no aplica).
        is_individual: ``True`` si es 個人 (necesario, pero no suficiente, para 特例).
        rules: Parametros del 消費税 del anio.
        as_of: Fecha de referencia para 2割 vs 3割特例.

    Returns:
        `ConsumptionResult` con escenarios; elegibilidad y recomendaciones
        requieren información fiscal que todavía no se recopila.
    """
    sales = _sales_breakdown(sources, rules)
    purchases = _purchase_breakdown(confirmed, rules)
    sales_tax = sales.national_tax_total

    # 本則課税: 仕入税額控除 = consumo real de los gastos con 適格請求書.
    honsoku = _make_option(
        ConsumptionMethodKey.HONSOKU,
        "本則課税",
        eligible=False,
        eligibility_status="unverified" if is_taxable else "unavailable",
        sales_tax=sales_tax,
        purchase_tax_credit=purchases.national_tax_total,
        rules=rules,
        note="登録番号の形式からの仮計算。登録・請求書は未検証",
    )

    # 簡易課税: 仕入税額控除 = 売上税額 × みなし仕入率 (segun 事業区分).
    deemed_rate = (
        rules.deemed_rate_for(business_category)
        if business_category is not None
        else 0.0
    )
    kani_credit = int(sales_tax * deemed_rate)
    kani_note = (
        f"みなし仕入率 {int(deemed_rate * 100)}%"
        f"（{BUSINESS_CATEGORY_LABELS.get(business_category or 0, '事業区分未設定')}）"
        if business_category is not None
        else "事業区分の設定が必要です"
    )
    kani = _make_option(
        ConsumptionMethodKey.KANI,
        "簡易課税",
        eligible=False,
        eligibility_status="unverified" if is_taxable else "unavailable",
        sales_tax=sales_tax,
        purchase_tax_credit=kani_credit,
        rules=rules,
        note=kani_note,
    )

    # 2割特例 / 3割特例: 売上税額 × tasa (solo 個人; tasa por fecha).
    tokurei_rate, tokurei_label = _tokurei_rate(as_of, rules)
    tokurei_possible = is_taxable and is_individual and 2023 <= rules.year <= 2028
    tokurei_credit = int(sales_tax * (1 - tokurei_rate))
    tokurei = _make_option(
        ConsumptionMethodKey.TOKUREI,
        tokurei_label,
        eligible=False,
        eligibility_status="unverified" if tokurei_possible else "unavailable",
        sales_tax=sales_tax,
        purchase_tax_credit=tokurei_credit,
        rules=rules,
        note=(f"売上税額 × {int(tokurei_rate * 100)}%（個人事業者の特例。"
              "適用要件は別途確認が必要です）"),
    )

    return ConsumptionResult(
        year=rules.year,
        is_taxable=is_taxable,
        method_setting=method_setting,
        business_category=business_category,
        sales_breakdown=sales,
        purchase_breakdown=purchases,
        honsoku=honsoku,
        kani=kani,
        tokurei=tokurei,
        recommended=None,
        recommended_saving=0,
        as_of=as_of,
    )


# --- Entrada de alto nivel (desde la BD del 年度) ---------------------------


def calculate_consumption_for_year(
    session: Session,
    year: int,
    *,
    rules: TaxRules | None = None,
    as_of: date | None = None,
) -> ConsumptionResult:
    """Calcula el 消費税 del 年度 leyendo Taxpayer / IncomeSource / Transaction.

    Args:
        session: Sesion de SQLAlchemy.
        year: 年度 (令和7 = 2025).
        rules: Parametros fiscales; si es ``None`` se cargan por `year`.
        as_of: Fecha de referencia para 2割/3割特例; default = cierre del 年度.

    Returns:
        `ConsumptionResult` del 年度. Si el contribuyente es 免税事業者, devuelve
        un resultado vacio con `is_taxable=False`.

    Raises:
        ValueError: Si no existe el 年度 pedido.
        FileNotFoundError: Si no hay parametros fiscales para el anio.
    """
    if rules is None:
        rules = load_tax_rules(year)

    # Guard explícito: si el año fiscal no trae el bloque de reglas de 消費税,
    # NO seguimos hasta un AttributeError opaco en `calculate_consumption_tax`.
    # `load_tax_rules` siempre lo provee (default + inyección del año), pero un
    # `TaxRules` armado a mano podría no tenerlo: fallamos con un mensaje claro.
    if getattr(rules, "consumption", None) is None:
        raise ValueError(
            f"No hay reglas de 消費税 (consumption) para el 年度 {year}. "
            "Revisar app/tax_rules/{year}.json o los parámetros pasados."
        )

    fiscal_year = session.scalars(
        select(FiscalYear).where(FiscalYear.year == year)
    ).first()
    if fiscal_year is None:
        raise ValueError(f"No existe el 年度 {year}.")

    taxpayer = fiscal_year.taxpayer
    is_taxable = bool(taxpayer.is_taxable_consumption) if taxpayer else False
    raw_method = taxpayer.consumption_method if taxpayer else None
    method_setting = getattr(raw_method, "value", raw_method)
    business_category = _business_category(taxpayer)
    # En el MVP single-user el contribuyente es 個人事業主 (siempre 個人).
    is_individual = True

    sources = list(
        session.scalars(
            select(IncomeSource).where(
                IncomeSource.fiscal_year_id == fiscal_year.id
            )
        ).all()
    )
    confirmed = list(
        session.scalars(
            select(Transaction).where(
                Transaction.fiscal_year_id == fiscal_year.id,
                Transaction.status == TransactionStatus.CONFIRMED,
            )
        ).all()
    )

    resolved_as_of = as_of or date(year, 12, 31)
    return calculate_consumption_tax(
        sources=sources,
        confirmed=confirmed,
        is_taxable=is_taxable,
        method_setting=method_setting,
        business_category=business_category,
        is_individual=is_individual,
        rules=rules.consumption,
        as_of=resolved_as_of,
    )


def _business_category(taxpayer: object) -> int | None:
    """Extrae el 事業区分 (1〜6) del `business_category` del Taxpayer.

    El 事業区分 del 簡易課税 se persiste en `Taxpayer.consumption_business_category`
    (entero 1〜6) cuando el modelo lo expone; si no, se infiere ``None``.

    Args:
        taxpayer: Entidad `Taxpayer` (o ``None``).

    Returns:
        El 事業区分 (1〜6) o ``None`` si no esta configurado.
    """
    if taxpayer is None:
        return None
    raw = getattr(taxpayer, "consumption_business_category", None)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= 6 else None
