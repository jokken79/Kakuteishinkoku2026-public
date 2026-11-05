"""Loader de parametros fiscales por anio (capa directiva).

Lee el JSON `app/tax_rules/{year}.json` y lo valida con un modelo Pydantic.
Los parametros (tablas de 速算表, 基礎控除 escalonado, topes de 控除, etc.) son
**configuracion parametrizada por anio fiscal** — nunca hardcodear tasas ni
umbrales en la logica de calculo (regla research 01 §0).

El resultado se cachea por anio: cargar el mismo anio dos veces devuelve la
misma instancia inmutable.
"""

import json
import logging
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Directorio donde viven los JSON de parametros por anio: app/tax_rules/
_RULES_DIR = Path(__file__).resolve().parent.parent / "tax_rules"


class KisoKojoBracket(BaseModel):
    """Tramo de la tabla de 基礎控除 escalonado (reforma 令和7).

    Args:
        max_income: 合計所得金額 maximo (inclusive) para este tramo. `None`
            representa el tramo sin tope superior (mayores ingresos).
        amount: Monto del 基礎控除 aplicable en este tramo.
        temporary: True si el monto es una medida temporal de 令和7・8年.
    """

    max_income: int | None
    amount: int
    temporary: bool = False


class IncomeTaxBracket(BaseModel):
    """Tramo del 速算表 del 所得税 (tasa + 控除額).

    所得税額 = 課税所得 × rate − deduction (research 01 §0).

    Args:
        max: 課税所得金額 maximo (inclusive) de este tramo. `None` = sin tope.
        rate: Tasa marginal aplicable.
        deduction: 控除額 (constante de ajuste del 速算表).
    """

    max: int | None
    rate: float
    deduction: int


class AoiroSpecialDeduction(BaseModel):
    """Montos del 青色申告特別控除 segun modalidad.

    Args:
        double_entry_etax: 複式簿記 + e-Tax / 優良電子帳簿 (¥650,000).
        double_entry_paper: 複式簿記 en papel (¥550,000).
        simple: 簡易簿記 / partida simple (¥100,000).
    """

    double_entry_etax: int
    double_entry_paper: int
    simple: int


class DeductionLimits(BaseModel):
    """Topes y pisos de varias 所得控除.

    Args:
        jishin_hoken_max: Tope del 地震保険料控除.
        seimei_hoken_max: Tope del 生命保険料控除.
        iryohi_floor: Piso fijo del 医療費控除 (¥100,000) — se compara con el
            5% del 総所得 y se usa el menor.
        furusato_floor: Monto no deducible del 寄附金控除 (¥2,000).
    """

    jishin_hoken_max: int
    seimei_hoken_max: int
    iryohi_floor: int
    furusato_floor: int


class ResidentTaxRules(BaseModel):
    """Parametros del 住民税 (impuesto de residencia) de un anio.

    El 住民税 se paga al AÑO SIGUIENTE (jun-may) y usa deducciones DISTINTAS al
    所得税 (research 住民税): 基礎控除 ¥430,000 (no escalonado), 扶養控除 menores y
    SIN 復興特別税. Estructura: 所得割 (課税住民 × 10%, repartido 県4%/市6%) +
    均等割 (県+市+森林環境税) − 調整控除 (ajuste por la diferencia de 人的控除 entre
    所得税 y 住民税, tabla fija del 国税庁).

    Args:
        kiso_kojo: 基礎控除 del 住民税 (¥430,000 en 令和7, plano hasta 合計所得 ¥24M).
        shotokuwari_prefectural_rate: Tasa del 所得割 県民税 (0.04).
        shotokuwari_municipal_rate: Tasa del 所得割 市民税 (0.06).
        kintowari_prefectural: 均等割 県民税 (¥1,500 en 津島市; incluye あいち森と緑
            づくり税 ¥500).
        kintowari_municipal: 均等割 市民税 (¥3,000 en 津島市).
        forest_environment_tax: 森林環境税 (¥1,000 nacional, desde 令和6).
        chosei_kojo_basic_diff: 人的控除差 del 基礎控除 para el 調整控除 (¥50,000,
            tabla fija — NO la diferencia escalonada bruta).
        chosei_kojo_dependent_diff: 人的控除差 por categoria de 扶養親族 (clave =
            valor de `DependentKind`), para el 調整控除.
        chosei_kojo_low_rate: Tasa del 調整控除 para 課税住民 <= umbral (0.05).
        chosei_kojo_threshold: Umbral del 課税住民 (¥2,000,000) que separa la
            formula plena (<=) de la reducida (>).
        chosei_kojo_min: Piso del 調整控除 en la rama > umbral (¥2,500).
        taxable_rounding: Redondeo a la baja del 課税住民 (¥1,000).
        source: Citas de las fuentes oficiales (trazabilidad).
    """

    kiso_kojo: int = 430_000
    shotokuwari_prefectural_rate: float = 0.04
    shotokuwari_municipal_rate: float = 0.06
    kintowari_prefectural: int = 1_500
    kintowari_municipal: int = 3_000
    forest_environment_tax: int = 1_000
    chosei_kojo_basic_diff: int = 50_000
    chosei_kojo_dependent_diff: dict[str, int] = {
        "general": 50_000,
        "specific": 180_000,
        "elderly": 100_000,
        "elderly_cohabiting": 130_000,
        "young": 0,
        "none": 0,
    }
    chosei_kojo_low_rate: float = 0.05
    chosei_kojo_threshold: int = 2_000_000
    chosei_kojo_min: int = 2_500
    taxable_rounding: int = 1_000
    source: str = ""

    def dependent_diff_for(self, kind_value: str) -> int:
        """Devuelve el 人的控除差 del 調整控除 de un 扶養親族 por categoria.

        Args:
            kind_value: Valor de `DependentKind` (ej. ``"elderly"``).

        Returns:
            人的控除差 (¥) de esa categoria; 0 si la categoria es desconocida.
        """
        return self.chosei_kojo_dependent_diff.get(kind_value, 0)


class ConsumptionRules(BaseModel):
    """Parametros del 消費税 (impuesto al consumo) de un anio (research 01 §6).

    Todo lo que el motor del 消費税 necesita, parametrizado por anio fiscal:
    tasas (estandar / reducida), reparto nacional/local, みなし仕入率 del 簡易課税
    por 事業区分, y las tasas/fechas del 2割特例 → 3割特例.

    Args:
        year: Anio fiscal (se inyecta desde `TaxRules.year`).
        standard_rate: Tasa estandar (10).
        reduced_rate: Tasa reducida 軽減税率 (8).
        national_rate_standard: Parte nacional del 10% (7.8).
        national_rate_reduced: Parte nacional del 8% (6.24).
        local_tax_ratio_num: Numerador del ratio 地方/国 (22).
        local_tax_ratio_den: Denominador del ratio 地方/国 (78).
        deemed_purchase_rates: みなし仕入率 por 事業区分 (clave "1".."6").
        tokurei_2wari_rate: Tasa del 2割特例 (0.20).
        tokurei_3wari_rate: Tasa del 3割特例 (0.30).
        tokurei_2wari_until: Ultima fecha (inclusive) en que rige el 2割特例;
            despues rige el 3割特例 (ISO date). ``None`` = sin corte (siempre 2割).
    """

    year: int = 0
    standard_rate: int = 10
    reduced_rate: int = 8
    national_rate_standard: float = 7.8
    national_rate_reduced: float = 6.24
    local_tax_ratio_num: int = 22
    local_tax_ratio_den: int = 78
    deemed_purchase_rates: dict[str, float] = {
        "1": 0.90,
        "2": 0.80,
        "3": 0.70,
        "4": 0.60,
        "5": 0.50,
        "6": 0.40,
    }
    tokurei_2wari_rate: float = 0.20
    tokurei_3wari_rate: float = 0.30
    tokurei_2wari_until: date | None = date(2026, 9, 30)

    def national_rate_for(self, rate: int) -> float:
        """Devuelve la parte nacional (%) para una tasa total (8 o 10).

        Args:
            rate: Tasa total aplicada (8 o 10).

        Returns:
            Parte nacional en puntos porcentuales (7.8 o 6.24).
        """
        if rate == self.reduced_rate:
            return self.national_rate_reduced
        return self.national_rate_standard

    def deemed_rate_for(self, business_category: int) -> float:
        """Devuelve la みなし仕入率 (0.0-1.0) de un 事業区分 (1〜6).

        Args:
            business_category: 事業区分 (1〜6).

        Returns:
            みなし仕入率 (ej. 0.90 para 第1種). 0.0 si el区分 es desconocido.
        """
        return self.deemed_purchase_rates.get(str(business_category), 0.0)


class TaxRules(BaseModel):
    """Parametros fiscales validados de un anio.

    Args:
        year: Anio fiscal (ej. 2025).
        era: Era japonesa correspondiente (ej. "令和7").
        kiso_kojo: Tabla escalonada del 基礎控除.
        income_tax_brackets: 速算表 del 所得税.
        reconstruction_tax_rate: Tasa del 復興特別所得税 (0.021).
        salary_deduction_min: 給与所得控除 minimo.
        dependent_income_threshold: Umbral de ingreso para dependiente/conyuge
            (¥580,000 en 令和7).
        aoiro_special_deduction: Montos del 青色申告特別控除.
        consumption_tokurei_rate: Tasa del 2割特例 de 消費税 (no usado por M3).
        deductions: Topes y pisos de las 所得控除.
        resident_tax: Parametros del 住民税 (impuesto de residencia).
    """

    year: int
    era: str
    kiso_kojo: list[KisoKojoBracket]
    income_tax_brackets: list[IncomeTaxBracket]
    reconstruction_tax_rate: float
    salary_deduction_min: int
    dependent_income_threshold: int
    aoiro_special_deduction: AoiroSpecialDeduction
    consumption_tokurei_rate: float = 0.20
    consumption: ConsumptionRules = ConsumptionRules()
    deductions: DeductionLimits
    resident_tax: ResidentTaxRules = ResidentTaxRules()

    def kiso_kojo_for(self, total_income: int) -> int:
        """Devuelve el 基礎控除 segun el 合計所得金額.

        Recorre la tabla escalonada y devuelve el monto del primer tramo cuyo
        `max_income` cubre el ingreso (o el tramo sin tope).

        Args:
            total_income: 合計所得金額 del contribuyente.

        Returns:
            Monto del 基礎控除 aplicable.
        """
        for bracket in self.kiso_kojo:
            if bracket.max_income is None or total_income <= bracket.max_income:
                return bracket.amount
        # Defensa: la tabla siempre debe tener un tramo final con max_income None.
        return 0

    def bracket_for(self, taxable_income: int) -> IncomeTaxBracket:
        """Devuelve el tramo del 速算表 para un 課税所得 dado.

        Args:
            taxable_income: 課税所得金額 (ya redondeado a la baja).

        Returns:
            Tramo (`IncomeTaxBracket`) aplicable.
        """
        for bracket in self.income_tax_brackets:
            if bracket.max is None or taxable_income <= bracket.max:
                return bracket
        return self.income_tax_brackets[-1]


@lru_cache
def load_tax_rules(year: int) -> TaxRules:
    """Carga y valida los parametros fiscales de un anio (cacheado).

    Args:
        year: Anio fiscal cuyo JSON cargar (`app/tax_rules/{year}.json`).

    Returns:
        Instancia validada de `TaxRules`.

    Raises:
        FileNotFoundError: Si no existe el JSON del anio pedido.
    """
    path = _RULES_DIR / f"{year}.json"
    if not path.is_file():
        raise FileNotFoundError(f"No hay parametros fiscales para el anio {year}: {path}")
    logger.info("Cargando parametros fiscales del anio %s desde %s", year, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = TaxRules(**data)
    # Inyectar el anio en los sub-parametros del 消費税 (para trazabilidad en el
    # resultado), sin requerir duplicarlo en el JSON.
    if rules.consumption.year == 0:
        rules.consumption.year = rules.year
    return rules
