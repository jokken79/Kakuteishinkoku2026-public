"""Construcción experimental del sobre RKO0010; todavía no genera declaraciones.

Los campos fiscales, anexos y validaciones de presentación se implementan por
separado. Ninguna ruta pública debe descargar el resultado de este módulo.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # nosec B405: el XML se construye en memoria
from dataclasses import dataclass, field
from datetime import date

SHOTOKU = "http://xml.e-tax.nta.go.jp/XSD/shotoku"
GENERAL = "http://xml.e-tax.nta.go.jp/XSD/general"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

# Prefijos convencionales del formato e-Tax para interoperabilidad del importador.
ET.register_namespace("", SHOTOKU)
ET.register_namespace("gen", GENERAL)
ET.register_namespace("rdf", RDF)


@dataclass(frozen=True)
class XtxIdentity:
    """Datos explícitos para IT; no se guardan ni se recuperan del perfil."""

    user_id: str = field(repr=False)
    name: str = field(repr=False)
    address: str = field(repr=False)
    office_code: str = field(repr=False)
    my_number: str | None = field(default=None, repr=False)
    birth_date: date | None = field(default=None, repr=False)


def _child(parent: ET.Element, name: str, **attrs: str) -> ET.Element:
    return ET.SubElement(parent, f"{{{SHOTOKU}}}{name}", attrs)


def date_children(parent: ET.Element, value: date) -> None:
    eras = (
        (date(2019, 5, 1), 5, 2018),
        (date(1989, 1, 8), 4, 1988),
        (date(1926, 12, 25), 3, 1925),
        (date(1912, 7, 30), 2, 1911),
        (date(1868, 1, 25), 1, 1867),
    )
    for start, code, offset in eras:
        if value >= start:
            for tag, text in (
                ("era", str(code)),
                ("yy", str(value.year - offset)),
                ("mm", str(value.month)),
                ("dd", str(value.day)),
            ):
                ET.SubElement(parent, f"{{{GENERAL}}}{tag}").text = text
            return
    raise ValueError("La fecha es anterior a las eras admitidas por el esquema.")


def build_experimental_envelope(
    identity: XtxIdentity,
    *,
    created_by: str,
    created_on: date,
    year: int = 2025,
    name_kana: str | None = None,
    postal_code: str | None = None,
    occupation: str | None = None,
) -> tuple[ET.Element, ET.Element]:
    """Crea RKO0010 y una página vacía para pruebas, no para presentar."""
    if not re.fullmatch(r"[0-9]{16}", identity.user_id):
        raise ValueError("El 利用者識別番号 debe contener 16 dígitos ASCII.")
    if not re.fullmatch(r"[0-9]{5}", identity.office_code):
        raise ValueError("El código de 税務署 debe contener 5 dígitos ASCII.")
    if not all(value.strip() for value in (identity.name, identity.address, created_by)):
        raise ValueError("Faltan datos obligatorios de identificación o creación.")

    if year != 2025:
        raise ValueError("El esquema verificado corresponde exclusivamente a 令和7 (2025).")
    if postal_code is not None and not re.fullmatch(r"[0-9]{3}-?[0-9]{4}", postal_code):
        raise ValueError("El código postal debe contener siete dígitos ASCII.")

    if identity.my_number is not None and not re.fullmatch(r"[0-9]{12}", identity.my_number):
        raise ValueError("El マイナンバー requiere doce dígitos ASCII sin enmascarar.")
    if identity.birth_date is not None and identity.birth_date > created_on:
        raise ValueError("La fecha de nacimiento es posterior a la creación.")

    root = ET.Element(f"{{{SHOTOKU}}}DATA", {"id": "DATA"})
    procedure = _child(root, "RKO0010", id="RKO0010", VR="25.0.0")
    catalog = _child(procedure, "CATALOG", id="CATALOG")
    rdf = ET.SubElement(catalog, f"{{{RDF}}}RDF")
    description = ET.SubElement(rdf, f"{{{RDF}}}Description", {"ID": "REPORT"})
    _child(description, "SEND_DATA")
    it_sec = _child(description, "IT_SEC")
    ET.SubElement(it_sec, f"{{{RDF}}}Description", {"about": "#IT"})
    form_sec = _child(description, "FORM_SEC")
    seq = ET.SubElement(form_sec, f"{{{RDF}}}Seq")
    item = ET.SubElement(seq, f"{{{RDF}}}li")
    ET.SubElement(item, f"{{{RDF}}}Description", {"about": "#KOA020-1"})
    for section in ("TENPU_SEC", "XBRL_SEC", "XBRL2_1_SEC", "SOFUSHO_SEC", "ATTACH_SEC", "CSV_SEC"):
        _child(description, section)

    contents = _child(procedure, "CONTENTS", id="CONTENTS")
    it = _child(contents, "IT", id="IT", VR="1.5")
    office = _child(it, "ZEIMUSHO", ID="ZEIMUSHO")
    ET.SubElement(office, f"{{{GENERAL}}}zeimusho_CD").text = identity.office_code
    _child(it, "NOZEISHA_ID", ID="NOZEISHA_ID").text = identity.user_id
    if identity.my_number:
        number = _child(it, "NOZEISHA_BANGO", ID="NOZEISHA_BANGO")
        ET.SubElement(number, f"{{{GENERAL}}}kojinbango").text = identity.my_number
    if name_kana:
        _child(it, "NOZEISHA_NM_KN", ID="NOZEISHA_NM_KN").text = name_kana
    _child(it, "NOZEISHA_NM", ID="NOZEISHA_NM").text = identity.name
    if postal_code:
        postal = _child(it, "NOZEISHA_ZIP", ID="NOZEISHA_ZIP")
        digits = postal_code.replace("-", "")
        ET.SubElement(postal, f"{{{GENERAL}}}zip1").text = digits[:3]
        ET.SubElement(postal, f"{{{GENERAL}}}zip2").text = digits[3:]
    _child(it, "NOZEISHA_ADR", ID="NOZEISHA_ADR").text = identity.address
    if identity.birth_date:
        date_children(_child(it, "BIRTHDAY", ID="BIRTHDAY"), identity.birth_date)
    if occupation:
        _child(it, "SHOKUGYO", ID="SHOKUGYO").text = occupation
    _child(_child(it, "TETSUZUKI", ID="TETSUZUKI"), "procedure_CD").text = "RKO0010"
    nenbun = _child(it, "NENBUN", ID="NENBUN")
    ET.SubElement(nenbun, f"{{{GENERAL}}}era").text = "5"
    ET.SubElement(nenbun, f"{{{GENERAL}}}yy").text = "7"
    _child(_child(it, "SHINKOKU_KBN", ID="SHINKOKU_KBN"), "kubun_CD").text = "1"
    form = _child(
        contents,
        "KOA020",
        id="KOA020-1",
        VR="23.0",
        softNM="Kakuteishinkoku",
        sakuseiNM=created_by,
        sakuseiDay=created_on.isoformat(),
    )
    page = _child(form, "KOA020-1")
    return root, page
