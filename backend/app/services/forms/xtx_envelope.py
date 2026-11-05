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


@dataclass(frozen=True)
class XtxIdentity:
    """Datos explícitos para IT; no se guardan ni se recuperan del perfil."""

    user_id: str = field(repr=False)
    name: str = field(repr=False)
    address: str = field(repr=False)
    office_code: str = field(repr=False)


def _child(parent: ET.Element, name: str, **attrs: str) -> ET.Element:
    return ET.SubElement(parent, f"{{{SHOTOKU}}}{name}", attrs)


def build_experimental_envelope(
    identity: XtxIdentity, *, created_by: str, created_on: date
) -> tuple[ET.Element, ET.Element]:
    """Crea RKO0010 y una página vacía para pruebas, no para presentar."""
    if not re.fullmatch(r"[0-9]{16}", identity.user_id):
        raise ValueError("El 利用者識別番号 debe contener 16 dígitos ASCII.")
    if not re.fullmatch(r"[0-9]{5}", identity.office_code):
        raise ValueError("El código de 税務署 debe contener 5 dígitos ASCII.")
    if not all(value.strip() for value in (identity.name, identity.address, created_by)):
        raise ValueError("Faltan datos obligatorios de identificación o creación.")

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
    _child(it, "NOZEISHA_NM", ID="NOZEISHA_NM").text = identity.name
    _child(it, "NOZEISHA_ADR", ID="NOZEISHA_ADR").text = identity.address
    _child(_child(it, "TETSUZUKI", ID="TETSUZUKI"), "procedure_CD").text = "RKO0010"
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
