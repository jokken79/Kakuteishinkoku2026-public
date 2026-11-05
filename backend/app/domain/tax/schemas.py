"""Modelos Pydantic de entrada/salida de la calculadora fiscal del 所得税.

Toda la calculadora trabaja con montos enteros (JPY). El 事業所得 llega ya
calculado como entero (= PL del motor contable − 青色申告特別控除); este modulo
NO conoce los modelos SQLAlchemy.
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class IncomeKind(StrEnum):
    """Tipos de 所得 soportados por la calculadora (research 01 §2).

    Solo se modelan los tipos relevantes para el MVP del owner. Los tipos de
    tributacion separada (利子 源泉分離, 退職, 山林, 譲渡) quedan fuera de scope.
    """

    KYUYO = "kyuyo"  # 給与所得
    JIGYO = "jigyo"  # 事業所得
    ZATSU = "zatsu"  # 雑所得
    FUDOSAN = "fudosan"  # 不動産所得
    ICHIJI = "ichiji"  # 一時所得
    HAITO = "haito"  # 配当所得 (総合課税)


class DependentKind(StrEnum):
    """Categorias de 扶養控除 (research 08, 令和7).

    Montos 所得税: 一般 ¥380k / 特定(19-22) ¥630k / 老人別居 ¥480k / 同居老親 ¥580k.
    `NONE` y `YOUNG` no aportan 控除 pero se registran (年少 cuenta para 住民税非課税基準).
    """

    NONE = "none"  # No califica (ingreso > umbral, 事業専従者, 国外 30-69 sin motivo)
    YOUNG = "young"  # 年少扶養親族 (<16): registrar, sin 控除
    GENERAL = "general"  # 一般扶養親族 (16-18, 23-69)
    SPECIFIC = "specific"  # 特定扶養親族 (19-22)
    ELDERLY = "elderly"  # 老人扶養親族 (70+, 別居)
    ELDERLY_COHABITING = "elderly_cohabiting"  # 同居老親等 (70+, 同居)


class Residence(StrEnum):
    """Residencia del 扶養親族 (research 08: 国外居住扶養親族)."""

    DOMESTIC = "domestic"  # 国内居住
    OVERSEAS = "overseas"  # 国外居住 (requiere documentos extra + traduccion)


class Cohabitation(StrEnum):
    """Convivencia con el contribuyente (define 同居老親 vs 老人別居)."""

    TOGETHER = "together"  # 同居
    SEPARATE = "separate"  # 別居


class OverseasExemptionReason(StrEnum):
    """Motivo de excepcion para 国外居住 de 30-69 anios (research 08)."""

    STUDY = "study"  # 留学
    DISABILITY = "disability"  # 障害者
    REMITTANCE_380K = "remittance_380k"  # 送金額 38万円以上


class IncomeInput(BaseModel):
    """Una fuente de ingreso con los campos necesarios por tipo.

    Segun `kind` se usan distintos campos:
        - KYUYO: `revenue` (給与収入).
        - JIGYO: `amount` (事業所得 YA neto = PL − 青色特別控除).
        - ZATSU / FUDOSAN: `revenue` y `expenses` (収入 − 経費).
        - ICHIJI: `revenue` y `expenses` (収入 − 支出, antes del 特別控除 ¥500k).
        - HAITO: `amount` (配当所得 ya neto).

    Args:
        kind: Tipo de 所得.
        revenue: 収入金額 bruto (para KYUYO/ZATSU/FUDOSAN/ICHIJI).
        expenses: 必要経費 o 支出 (para ZATSU/FUDOSAN/ICHIJI).
        amount: 所得金額 ya neto (para JIGYO/HAITO).
        label: Etiqueta opcional para trazabilidad en el desglose.
    """

    kind: IncomeKind
    revenue: int = Field(default=0, ge=0)
    expenses: int = Field(default=0, ge=0)
    amount: int = Field(default=0)
    label: str | None = None


class Dependent(BaseModel):
    """Un familiar a cargo para el 扶養控除 (categoria ya resuelta).

    La calculadora pura solo necesita la categoria; la clasificacion (edad,
    ingreso, residencia, 国外居住…) se hace en `app.domain.tax.dependents`.

    Args:
        kind: Categoria del dependiente (ya clasificada).
    """

    kind: DependentKind


class DependentInput(BaseModel):
    """Datos crudos de un 扶養親族 para clasificar (research 08).

    Args:
        name: Nombre del familiar.
        relationship: 続柄 (parentesco, ej. "母").
        birth_date: 生年月日 (para calcular la edad al 31/12 del año fiscal).
        goukei_shotoku: 合計所得金額 del dependiente (vs umbral ¥580k 令和7).
        is_jigyo_senju: ``True`` si es 事業専従者 (excluye el 控除).
        residence: 国内 / 国外.
        country: Pais de residencia si es 国外 (ej. "ペルー").
        cohabitation: 同居 / 別居 (define 同居老親 vs 老人別居).
        overseas_exemption: Motivo de excepcion para 国外 30-69 (留学/障害者/送金38万)
            o ``None``.
        annual_remittance: 送金額 anual a este dependiente (para validar 国外 30-69
            con motivo 送金38万). Informativo.
    """

    name: str
    relationship: str | None = None
    birth_date: date | None = None
    goukei_shotoku: int | None = Field(default=None, ge=0)
    is_jigyo_senju: bool = False
    residence: Residence = Residence.DOMESTIC
    country: str | None = None
    cohabitation: Cohabitation = Cohabitation.TOGETHER
    eligible_cohabiting_ancestor: bool | None = None
    overseas_exemption: OverseasExemptionReason | None = None
    annual_remittance: int | None = Field(default=None, ge=0)


class DeductionInput(BaseModel):
    """Entradas de las 所得控除 (research 01 §3).

    Args:
        social_insurance: 社会保険料控除 (total pagado, sin tope).
        medical_expenses: 医療費 pagados (antes de aplicar piso/reembolso).
        medical_reimbursement: Reembolsos recibidos (seguros, etc.).
        life_insurance: 生命保険料控除 ya calculado por categorias (input directo,
            la calculadora solo aplica el tope global).
        earthquake_insurance: 地震保険料 pagado (se aplica el tope).
        ideco: 小規模企業共済等掛金控除 / iDeCo (total pagado, sin tope).
        furusato: ふるさと納税 / 寄附金 (total donado).
        dependents: Lista de familiares a cargo (扶養控除).
        spouse_deduction: 配偶者(特別)控除 ya determinado (input directo).
        disability_deduction: 障害者控除 (input directo).
        widow_single_parent_deduction: 寡婦 / ひとり親控除 (input directo).
        working_student_deduction: 勤労学生控除 (input directo).
    """

    social_insurance: int = Field(default=0, ge=0)
    medical_expenses: int = Field(default=0, ge=0)
    medical_reimbursement: int = Field(default=0, ge=0)
    life_insurance: int = Field(default=0, ge=0)
    earthquake_insurance: int = Field(default=0, ge=0)
    ideco: int = Field(default=0, ge=0)
    furusato: int = Field(default=0, ge=0)
    dependents: list[Dependent] = Field(default_factory=list)
    spouse_deduction: int = Field(default=0, ge=0)
    disability_deduction: int = Field(default=0, ge=0)
    ordinary_disability_self: bool = False
    widow_single_parent_deduction: int = Field(default=0, ge=0)
    working_student_deduction: int = Field(default=0, ge=0)


class WithholdingInput(BaseModel):
    """Pagos ya realizados que se descuentan del impuesto final.

    Args:
        withholding_tax: 源泉徴収税額 (retenciones en la fuente).
        estimated_prepayment: 予定納税額 (pagos a cuenta de jul/nov).
    """

    withholding_tax: int = Field(default=0, ge=0)
    estimated_prepayment: int = Field(default=0, ge=0)


class TaxCalculationInput(BaseModel):
    """Entrada completa de un calculo de 所得税.

    Args:
        year: Anio fiscal (selecciona el JSON de parametros).
        filing_type: Modalidad ("aoiro_65" / "aoiro_55" / "aoiro_10" / "shiroiro").
            Informativo: el 事業所得 ya llega neto del 青色特別控除.
        incomes: Fuentes de ingreso.
        deductions: Entradas de 所得控除.
        withholding: Retenciones y pagos a cuenta.
        tax_credits: 税額控除 totales ya determinados (住宅ローン/配当控除/外国税額).
    """

    year: int = 2025
    filing_type: str = "aoiro_65"
    incomes: list[IncomeInput] = Field(default_factory=list)
    deductions: DeductionInput = Field(default_factory=DeductionInput)
    withholding: WithholdingInput = Field(default_factory=WithholdingInput)
    tax_credits: int = Field(default=0, ge=0)


class IncomeBreakdownItem(BaseModel):
    """Detalle de un 所得 calculado.

    Args:
        kind: Tipo de 所得.
        label: Etiqueta de la fuente (si la hubo).
        amount: 所得金額 calculado (entero).
    """

    kind: IncomeKind
    label: str | None
    amount: int


class DeductionBreakdown(BaseModel):
    """Desglose de las 所得控除 aplicadas.

    Args:
        kiso: 基礎控除 (escalonado).
        social_insurance: 社会保険料控除.
        medical: 医療費控除.
        life_insurance: 生命保険料控除 (tras tope).
        earthquake_insurance: 地震保険料控除 (tras tope).
        dependents: 扶養控除 total.
        spouse: 配偶者(特別)控除.
        ideco: 小規模企業共済等掛金控除.
        furusato: 寄附金控除 (ふるさと納税).
        other: 障害者 + 寡婦/ひとり親 + 勤労学生 控除.
    """

    kiso: int
    social_insurance: int
    medical: int
    life_insurance: int
    earthquake_insurance: int
    dependents: int
    spouse: int
    ideco: int
    furusato: int
    other: int
    ordinary_disability_self: bool = False


class TaxCalculationResult(BaseModel):
    """Resultado completo del calculo de 所得税.

    Args:
        year: Anio fiscal usado.
        income_breakdown: Detalle de cada 所得.
        total_income: 合計所得金額 (Σ所得 de tributacion global).
        deduction_breakdown: Desglose de las 所得控除.
        total_income_deductions: Σ所得控除.
        taxable_income: 課税所得金額 (redondeado a la baja a ¥1,000).
        income_tax_base: 基準所得税額 (tras 速算表, antes de 復興税, sin negativos).
        tax_credits: 税額控除 aplicados.
        income_tax_after_credits: Impuesto tras 税額控除 (base de 復興税).
        reconstruction_tax: 復興特別所得税 (× 0.021).
        total_tax: 所得税 + 復興特別所得税 (年税額).
        withholding_total: 源泉徴収 + 予定納税.
        final_amount: 納付額 (>0) o 還付金 (<0). Negativo = devolucion.
    """

    year: int
    income_breakdown: list[IncomeBreakdownItem]
    total_income: int
    deduction_breakdown: DeductionBreakdown
    total_income_deductions: int
    taxable_income: int
    income_tax_base: int
    tax_credits: int
    income_tax_after_credits: int
    reconstruction_tax: int
    total_tax: int
    withholding_total: int
    withholding_tax: int = 0
    estimated_prepayment: int = 0
    final_amount: int
