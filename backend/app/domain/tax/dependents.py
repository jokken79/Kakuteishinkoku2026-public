"""Clasificacion de 扶養親族 (扶養控除 detallado + 国外居住) — research 08, 令和7.

Toma los datos crudos de un 扶養親族 (`DependentInput`) y determina:

    - su **categoria** (`DependentKind`): 一般 / 特定 / 老人別居 / 同居老親 / 年少 / 対象外;
    - el **monto** del 扶養控除 (所得税 y 住民税);
    - si es **国外居住扶養親族**, los **documentos requeridos** (research 08 tabla);
    - el **motivo** por el que NO califica (cuando aplica), para explicarlo en la UI.

Reglas clave (research 08):
    - Umbral de 合計所得金額 del dependiente: **¥580,000 (令和7)**. Si lo supera o es
      事業専従者 → 対象外 (sin 控除).
    - Edad al 31/12 del año fiscal: <16 年少 (sin 控除) · 19-22 特定 (¥630k) ·
      70+ 同居 同居老親 (¥580k) / 70+ 別居 老人別居 (¥480k) · resto 一般 (¥380k).
    - 国外居住 30-69 sin motivo (留学/障害者/送金38万) → **NO califica**.
    - 国外居住 (cualquier edad que califique) → requiere 親族関係書類 + 送金関係書類
      (+ 留学ビザ等 si el motivo es 留学; + 38万円送金書類 si el motivo es 送金38万),
      y SIEMPRE aviso de 翻訳文 (traduccion al japones) si los docs no estan en japones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from app.domain.tax.schemas import (
    Cohabitation,
    Dependent,
    DependentInput,
    DependentKind,
    OverseasExemptionReason,
    Residence,
)

logger = logging.getLogger(__name__)

# Umbral de 合計所得金額 del dependiente (令和7: subio de ¥480k a ¥580k). research 08.
DEPENDENT_INCOME_THRESHOLD = 580_000


def dependent_income_threshold(fiscal_year: int) -> int:
    """Límite de ingresos del dependiente para la liquidación anual.

    Fuente: NTA No.1180; la reforma de 2026 entra en vigor el 1 de diciembre.
    Años posteriores aún requieren reglas fiscales verificadas antes de calcular.
    """
    if fiscal_year == 2025:
        return DEPENDENT_INCOME_THRESHOLD
    if fiscal_year == 2026:
        return 620_000
    if 2020 <= fiscal_year <= 2024:
        return 480_000
    raise ValueError(f"No hay límite de dependientes verificado para {fiscal_year}")

# Montos del 扶養控除 por categoria (所得税, 住民税) — research 08 tabla 令和7.
# (所得税, 住民税). 年少 / 対象外 no aportan 控除.
DEPENDENT_AMOUNTS: dict[DependentKind, tuple[int, int]] = {
    DependentKind.GENERAL: (380_000, 330_000),
    DependentKind.SPECIFIC: (630_000, 450_000),
    DependentKind.ELDERLY: (480_000, 380_000),  # 老人別居
    DependentKind.ELDERLY_COHABITING: (580_000, 450_000),  # 同居老親
    DependentKind.YOUNG: (0, 0),
    DependentKind.NONE: (0, 0),
}

# Codigos estables de documentos requeridos (国外居住扶養親族). research 08.
DOC_RELATIONSHIP = "shinzoku_kankei"  # 親族関係書類
DOC_REMITTANCE = "soukin_kankei"  # 送金関係書類
DOC_STUDY_VISA = "ryugaku_visa"  # 留学ビザ等書類
DOC_REMITTANCE_380K = "soukin_38man"  # 38万円送金書類
DOC_TRANSLATION = "honyaku"  # 翻訳文 (aviso, no documento "tipo")


@dataclass(frozen=True)
class DependentResult:
    """Resultado de clasificar un 扶養親族.

    Args:
        name: Nombre del familiar (passthrough para la UI).
        kind: Categoria resuelta.
        age: Edad calculada al 31/12 del año fiscal (o ``None`` si no hay fecha).
        income_tax_amount: 扶養控除 del 所得税 (¥).
        resident_tax_amount: 扶養控除 del 住民税 (¥).
        qualifies: ``True`` si aporta 控除 al 所得税 (kind != YOUNG/NONE).
        is_overseas: ``True`` si es 国外居住扶養親族.
        required_documents: Codigos de documentos requeridos (国外) — vacio si 国内.
        needs_translation: ``True`` si hace falta 翻訳文 (国外 con docs no-japoneses).
        disqualified_reason: Motivo por el que NO califica (clave), o ``None``.
    """

    name: str
    kind: DependentKind
    age: int | None
    income_tax_amount: int
    resident_tax_amount: int
    qualifies: bool
    is_overseas: bool
    required_documents: list[str] = field(default_factory=list)
    needs_translation: bool = False
    disqualified_reason: str | None = None

    def to_dependent(self) -> Dependent:
        """Proyecta a `Dependent` (lo que consume la calculadora pura)."""
        return Dependent(kind=self.kind)


def age_at_year_end(birth: date | None, fiscal_year: int) -> int | None:
    """Calcula la edad al 31 de diciembre del año fiscal (research 08).

    Args:
        birth: 生年月日 o ``None``.
        fiscal_year: Año fiscal (ej. 2025 → edad al 2025-12-31).

    Returns:
        Edad en años cumplidos al 31/12 del año, o ``None`` si no hay fecha.
    """
    if birth is None:
        return None
    ref = date(fiscal_year, 12, 31)
    age = ref.year - birth.year
    # La edad legal se alcanza al finalizar el día anterior al cumpleaños;
    # quien nace el 1 de enero alcanza la edad el 31 de diciembre precedente.
    if birth.month == 1 and birth.day == 1 and birth <= ref:
        age += 1
    elif (ref.month, ref.day) < (birth.month, birth.day):
        age -= 1
    return max(age, 0)


def _category_by_age(
    age: int, cohabitation: Cohabitation, eligible_cohabiting_ancestor: bool | None
) -> DependentKind:
    """Devuelve la categoria por edad (asumiendo que ya califica). research 08.

    Args:
        age: Edad al 31/12.
        cohabitation: 同居 / 別居 (para 70+).

    Returns:
        Categoria del 扶養親族.
    """
    if age < 16:
        return DependentKind.YOUNG  # 年少: registra, sin 控除
    if 19 <= age <= 22:
        return DependentKind.SPECIFIC  # 特定扶養親族
    if age >= 70:
        if cohabitation == Cohabitation.TOGETHER and eligible_cohabiting_ancestor is True:
            return DependentKind.ELDERLY_COHABITING  # 同居老親等
        return DependentKind.ELDERLY  # 老人別居
    return DependentKind.GENERAL  # 一般 (16-18, 23-69)


def _overseas_qualifies(
    age: int, exemption: OverseasExemptionReason | None
) -> bool:
    """Determina si un 国外居住 califica segun edad/motivo (research 08).

    Args:
        age: Edad al 31/12.
        exemption: Motivo de excepcion (留学/障害者/送金38万) o ``None``.

    Returns:
        ``True`` si el 国外居住 califica para 控除.
    """
    if age < 30 or age >= 70:
        # 16-29 y 70+ califican siempre (con documentos). <16 es 年少 (se trata aparte).
        return True
    # 30-69: solo con motivo de excepcion (留学 / 障害者 / 送金38万).
    return exemption is not None


def _overseas_documents(
    kind: DependentKind, exemption: OverseasExemptionReason | None
) -> list[str]:
    """Lista los documentos requeridos para un 国外居住扶養親族 (research 08).

    Args:
        kind: Categoria resuelta (para no pedir docs a 年少/対象外).
        exemption: Motivo de excepcion (define docs extra).

    Returns:
        Codigos de documentos requeridos (親族関係 + 送金 + extras segun motivo).
    """
    if kind in (DependentKind.NONE,):
        return []
    docs = [DOC_RELATIONSHIP, DOC_REMITTANCE]
    if exemption == OverseasExemptionReason.STUDY:
        docs.append(DOC_STUDY_VISA)
    if exemption == OverseasExemptionReason.REMITTANCE_380K:
        docs.append(DOC_REMITTANCE_380K)
    return docs


def classify_dependent(dep: DependentInput, fiscal_year: int) -> DependentResult:
    """Clasifica un 扶養親族: categoria, monto, 国外 docs (research 08).

    Pipeline:
        1. 事業専従者 o 合計所得金額 > ¥580k → 対象外 (sin 控除).
        2. Edad al 31/12: <16 → 年少 (sin 控除, registrar).
        3. 国外居住 30-69 sin motivo → 対象外.
        4. Categoria por edad/同居 → monto 所得税/住民税.
        5. Si 国外 → documentos requeridos + aviso de 翻訳文.

    Args:
        dep: Datos crudos del 扶養親族.
        fiscal_year: Año fiscal (para la edad al 31/12).

    Returns:
        `DependentResult` con la categoria, montos y documentos.
    """
    age = age_at_year_end(dep.birth_date, fiscal_year)
    is_overseas = dep.residence == Residence.OVERSEAS

    def disqualified(reason: str) -> DependentResult:
        """Construye un resultado 対象外 con el motivo dado."""
        docs = _overseas_documents(DependentKind.NONE, dep.overseas_exemption)
        return DependentResult(
            name=dep.name,
            kind=DependentKind.NONE,
            age=age,
            income_tax_amount=0,
            resident_tax_amount=0,
            qualifies=False,
            is_overseas=is_overseas,
            required_documents=docs,
            needs_translation=False,
            disqualified_reason=reason,
        )

    # 1. 事業専従者 o ingreso del dependiente sobre el umbral → 対象外.
    if dep.is_jigyo_senju:
        return disqualified("jigyo_senju")
    if dep.goukei_shotoku is None:
        return disqualified("income_unknown")
    if dep.goukei_shotoku > dependent_income_threshold(fiscal_year):
        return disqualified("income_over_threshold")

    if age is None:
        return disqualified("birth_date_unknown")
    effective_age = age

    # 2. 年少扶養 (<16): registra, sin 控除 (pero NO es "対象外", es 年少).
    if effective_age < 16:
        kind = DependentKind.YOUNG
        docs = _overseas_documents(kind, dep.overseas_exemption) if is_overseas else []
        return DependentResult(
            name=dep.name,
            kind=kind,
            age=age,
            income_tax_amount=0,
            resident_tax_amount=0,
            qualifies=False,
            is_overseas=is_overseas,
            required_documents=docs,
            needs_translation=is_overseas and bool(docs),
            disqualified_reason=None,
        )

    # 3. 国外居住 30-69 sin motivo de excepcion → 対象外.
    if is_overseas and not _overseas_qualifies(effective_age, dep.overseas_exemption):
        return disqualified("overseas_30_69_no_reason")
    if (is_overseas and 30 <= effective_age < 70
            and dep.overseas_exemption == OverseasExemptionReason.REMITTANCE_380K):
        if dep.annual_remittance is None:
            return disqualified("remittance_unknown")
        if dep.annual_remittance < 380_000:
            return disqualified("remittance_below_380k")

    # 4. Categoria por edad / 同居 → monto.
    kind = _category_by_age(effective_age, dep.cohabitation, dep.eligible_cohabiting_ancestor)
    income_tax_amount, resident_tax_amount = DEPENDENT_AMOUNTS.get(kind, (0, 0))

    # 5. Documentos del 国外居住扶養親族 + aviso de 翻訳文.
    exemption = dep.overseas_exemption if 30 <= effective_age < 70 else None
    docs = _overseas_documents(kind, exemption) if is_overseas else []

    return DependentResult(
        name=dep.name,
        kind=kind,
        age=age,
        income_tax_amount=income_tax_amount,
        resident_tax_amount=resident_tax_amount,
        qualifies=income_tax_amount > 0,
        is_overseas=is_overseas,
        required_documents=docs,
        needs_translation=is_overseas and bool(docs),
        disqualified_reason=None,
    )


def classify_dependents(
    deps: list[DependentInput], fiscal_year: int
) -> list[DependentResult]:
    """Clasifica una lista de 扶養親族.

    Args:
        deps: Datos crudos de los familiares a cargo.
        fiscal_year: Año fiscal (para la edad al 31/12).

    Returns:
        Lista de `DependentResult` (mismo orden que la entrada).
    """
    return [classify_dependent(d, fiscal_year) for d in deps]
