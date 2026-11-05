"""Validador estructural del .xtx contra el esquema oficial KOA020 (令和7).

Comprueba que el XML generado por ``etax_export.build_xtx`` respeta el esquema
del NTA **extraído en** ``etax_schema_r7.json`` (research 10, del CAB oficial
``e-tax09.CAB``). NO es validación XSD formal — esa requiere el ``e-tax19.CAB``
(XMLスキーマ) del NTA; ver ``validate_xtx_against_xsd`` para el camino cuando se
disponga del XSD. Este validador cubre, sin material licenciado:

    1. Prólogo XML exacto (UTF-8, standalone="no").
    2. Buen formato (well-formed) y sobre ``<DATA>``.
    3. Sobre ``KOA020`` con ``VR`` esperada y jerarquía
       ``KOA020 → KOA020-1 → ABA00000 (cabecera) + ABB00000 (cuerpo)``.
    4. **Todo tag de campo emitido existe en el esquema confirmado** (no inventar
       tags: un tag desconocido rompe el envío real al NTA).
    5. Ausencia del bloque ``KOA210`` (decremento del XML; va por CSV).
    6. Formato de montos (entero sin separadores) y redondeos legales
       (課税所得 千円, 申告納税額/納付額 百円, 基礎控除 万円).
    7. 年分 (Gengo 1-5, Nen 2 dígitos) coherente con el año fiscal.

Devuelve un ``XtxReport`` con errores/avisos y la cobertura de campos.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

_SCHEMA_PATH = Path(__file__).resolve().parent / "etax_schema_r7.json"
_FIELD_TAG_RE = re.compile(r"^[A-Z]{3}\d{5}$")
_SEPARATOR_RE = re.compile(r"^-?\d{1,3}(,\d{3})+$")
_INT_RE = re.compile(r"^-?\d+$")

_PROLOG = b'<?xml version="1.0" encoding="UTF-8" standalone="no" ?>'

# Contenedores estructurales (no son tags de campo ABA/ABB…).
_CONTAINERS = {"DATA", "KOA020", "KOA020-1", "ABA00000", "ABB00000"}
# Sub-elementos compuestos permitidos (年分 / fechas con 元号).
_COMPOSITE_CHILDREN = {"Gengo", "Nen", "Tsuki", "Hi"}

# Redondeos legales por tag (el valor debe ser múltiplo de N).
_ROUNDING: dict[str, int] = {
    "ABB00580": 1000,   # 課税される所得金額 — 千円未満切捨て.
    "ABB00720": 100,    # 申告納税額 — 百円未満切捨て.
    "ABB00750": 100,    # 第3期分 納める税金 — 百円未満切捨て.
    "ABB00650": 100,    # 住宅借入金等特別控除 — 百円未満切捨て.
    "ABB00550": 10000,  # 基礎控除 — 万円未満切捨て.
}

# Bloques retirados del XML que NO deben aparecer (irían por CSV).
_RETIRED_FORMS = {"KOA210"}


@dataclass(frozen=True)
class XtxIssue:
    """Un hallazgo de validación."""

    level: Literal["error", "warning"]
    code: str
    message: str
    tag: str | None = None


@dataclass
class XtxReport:
    """Resultado de validar un .xtx."""

    ok: bool
    errors: int
    warnings: int
    issues: list[XtxIssue] = field(default_factory=list)
    emitted_field_tags: list[str] = field(default_factory=list)
    known_field_tags: int = 0

    def as_dict(self) -> dict[str, object]:
        """Serializa el reporte (para el endpoint / logs)."""
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "emitted_field_tags": self.emitted_field_tags,
            "known_field_tags": self.known_field_tags,
            "issues": [
                {"level": i.level, "code": i.code, "message": i.message, "tag": i.tag}
                for i in self.issues
            ],
        }


def load_valid_tags(schema_path: Path | None = None) -> frozenset[str]:
    """Carga el conjunto de tags de campo confirmados desde el JSON del esquema.

    Args:
        schema_path: Ruta al ``etax_schema_r7.json``. Si es ``None`` usa el
            empaquetado junto al módulo.

    Returns:
        Conjunto de tags ``[A-Z]{3}\\d{5}`` confirmados (cabecera + cuerpo +
        ejemplos confirmados del 第二表).
    """
    path = schema_path or _SCHEMA_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    form = data["forms"]["shinkokusho_dai1_dai2"]
    tags: set[str] = set()
    for value in form.get("header_fields", {}).values():
        if _FIELD_TAG_RE.match(str(value)):
            tags.add(str(value))
    for category in form.get("fields", {}).values():
        if isinstance(category, dict):
            for value in category.values():
                if _FIELD_TAG_RE.match(str(value)):
                    tags.add(str(value))
    for value in form.get("confirmed_tag_examples", {}).values():
        if _FIELD_TAG_RE.match(str(value)):
            tags.add(str(value))
    return frozenset(tags)


def _expected_vr(year: int) -> str:
    """VR esperada del 様式 KOA020 por año (令和7 = 23.0)."""
    # Por ahora solo 令和7 está extraído; otros años se agregan al parametrizar.
    return "23.0"


def validate_xtx(xtx: bytes, *, year: int = 2025, schema_path: Path | None = None) -> XtxReport:
    """Valida un .xtx contra el esquema confirmado KOA020.

    Args:
        xtx: Bytes del .xtx generado.
        year: Año fiscal (西暦) del que se espera el VR/元号.
        schema_path: Override del JSON del esquema (tests).

    Returns:
        ``XtxReport`` con ``ok=False`` si hay al menos un error.
    """
    issues: list[XtxIssue] = []
    valid_tags = load_valid_tags(schema_path)

    # 1) Prólogo exacto.
    first_line = xtx.split(b"\n", 1)[0].strip()
    if first_line != _PROLOG:
        issues.append(
            XtxIssue(
                "error",
                "prolog",
                f"Prólogo XML inesperado: {first_line!r} (debe ser {_PROLOG!r}).",
            )
        )

    # 2) Well-formed + parseo.
    try:
        root = ET.fromstring(xtx)
    except (ET.ParseError, DefusedXmlException) as exc:
        issues.append(XtxIssue("error", "not_well_formed", f"XML mal formado: {exc}"))
        return _finish(issues, [], len(valid_tags))

    # 3) Sobre <DATA>.
    if root.tag != "DATA":
        issues.append(
            XtxIssue("error", "root", f"La raíz debe ser <DATA>, no <{root.tag}>.")
        )

    # 4) KOA020 + VR.
    forms = [c for c in root if c.tag == "KOA020"]
    if not forms:
        issues.append(XtxIssue("error", "missing_form", "Falta el 様式 <KOA020>."))
    for form_el in forms:
        vr = form_el.get("VR")
        if vr != _expected_vr(year):
            issues.append(
                XtxIssue(
                    "warning",
                    "vr_mismatch",
                    f"VR={vr!r}; se esperaba {_expected_vr(year)!r} para {year}.",
                    tag="KOA020",
                )
            )
        page1 = [c for c in form_el if c.tag == "KOA020-1"]
        if not page1:
            issues.append(
                XtxIssue("error", "missing_page", "Falta <KOA020-1> (第一表).", tag="KOA020")
            )
        for page in page1:
            child_tags = {c.tag for c in page}
            if "ABA00000" not in child_tags:
                issues.append(
                    XtxIssue("error", "missing_header", "Falta <ABA00000> (cabecera).")
                )
            if "ABB00000" not in child_tags:
                issues.append(
                    XtxIssue("warning", "missing_body", "Falta <ABB00000> (cuerpo 第一表).")
                )

    # 5) Bloques retirados (KOA210).
    for el in root.iter():
        if el.tag in _RETIRED_FORMS:
            issues.append(
                XtxIssue(
                    "error",
                    "retired_form",
                    f"<{el.tag}> está retirado del XML (va por CSV); no debe emitirse.",
                    tag=el.tag,
                )
            )

    # 6) Tags de campo: existencia en el esquema + formato de montos.
    emitted: list[str] = []
    for el in root.iter():
        tag = el.tag
        if tag in _CONTAINERS or tag in _COMPOSITE_CHILDREN:
            continue
        if not _FIELD_TAG_RE.match(tag):
            # Tag no estructural y con forma no-campo → sospechoso.
            issues.append(
                XtxIssue("warning", "non_field_tag", f"Tag no reconocido: <{tag}>.", tag=tag)
            )
            continue
        emitted.append(tag)
        if tag not in valid_tags:
            issues.append(
                XtxIssue(
                    "error",
                    "unknown_tag",
                    f"<{tag}> no está en el esquema confirmado (rompería el envío).",
                    tag=tag,
                )
            )
        text = (el.text or "").strip()
        if text:
            _check_amount(tag, text, issues)

    # 7) 年分 (元号/年).
    _check_nenbun(root, year, issues)

    return _finish(issues, emitted, len(valid_tags))


def _check_amount(tag: str, text: str, issues: list[XtxIssue]) -> None:
    """Valida formato de monto y redondeo legal de un campo."""
    if _SEPARATOR_RE.match(text):
        issues.append(
            XtxIssue(
                "error",
                "amount_separator",
                f"<{tag}>={text!r} lleva separadores de miles; debe ir entero sin comas.",
                tag=tag,
            )
        )
        return
    unit = _ROUNDING.get(tag)
    if unit is not None and _INT_RE.match(text):
        if int(text) % unit != 0:
            issues.append(
                XtxIssue(
                    "warning",
                    "rounding",
                    f"<{tag}>={text} no es múltiplo de {unit} (redondeo legal).",
                    tag=tag,
                )
            )


def _check_nenbun(root: Any, year: int, issues: list[XtxIssue]) -> None:
    """Valida el 年分 (ABA00010 → Gengo/Nen)."""
    for nenbun in root.iter("ABA00010"):
        gengo = nenbun.findtext("Gengo")
        nen = nenbun.findtext("Nen")
        if gengo is not None and gengo not in {"1", "2", "3", "4", "5"}:
            issues.append(
                XtxIssue("error", "era_kubun", f"元号区分 inválido: {gengo!r}.", tag="ABA00010")
            )
        if year >= 2019 and gengo not in (None, "5"):
            issues.append(
                XtxIssue(
                    "warning",
                    "era_year",
                    f"Para {year} se espera 元号=5 (令和), no {gengo!r}.",
                    tag="ABA00010",
                )
            )
        if nen is not None and not re.fullmatch(r"\d{2}", nen):
            issues.append(
                XtxIssue("error", "nen_format", f"年 debe ser 2 dígitos: {nen!r}.", tag="ABA00010")
            )
        elif nen is not None and gengo == "5" and int(nen) != year - 2018:
            issues.append(
                XtxIssue(
                    "warning",
                    "nen_value",
                    f"年={nen} no coincide con 令和{year - 2018} para {year}.",
                    tag="ABA00010",
                )
            )


def _finish(issues: list[XtxIssue], emitted: list[str], known: int) -> XtxReport:
    """Arma el reporte final contando errores/avisos."""
    errors = sum(1 for i in issues if i.level == "error")
    warnings = sum(1 for i in issues if i.level == "warning")
    return XtxReport(
        ok=errors == 0,
        errors=errors,
        warnings=warnings,
        issues=issues,
        emitted_field_tags=sorted(set(emitted)),
        known_field_tags=known,
    )
