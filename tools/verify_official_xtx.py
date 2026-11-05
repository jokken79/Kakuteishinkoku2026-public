"""Comprueba el XML heredado con datos sintéticos contra el XSD oficial local.

Uso desde backend: python ../tools/verify_official_xtx.py RUTA/RKO0010-250.xsd
Requiere lxml y el árbol completo del CAB oficial descomprimido. Nunca abre la BD local.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as std_et
from datetime import date
from pathlib import Path

# El proyecto aislado debe preceder cualquier instalación editable del equipo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from lxml import etree

from app.db.session import create_db_engine, get_session_factory
from app.models import Base
from app.seed.dev_seed import seed_demo_data
from app.services.forms import etax_schema_r7 as fields
from app.services.forms.drafting import build_filing_draft
from app.services.forms.etax_export import build_xtx
from app.services.forms.xtx_envelope import XtxIdentity, build_experimental_envelope


def _empty_control() -> etree._Element:
    """Sobre sintético: comprueba XSD y RDF, no aptitud para presentar."""
    identity = XtxIdentity("0000000000000000", "架空 太郎", "架空住所", "01143")
    root, _ = build_experimental_envelope(identity, created_by="test", created_on=date(2026, 1, 1))
    return etree.fromstring(std_et.tostring(root, encoding="utf-8"))


def _mapped_control(payload: bytes, form_xsd: Path) -> tuple[etree._Element, int, int]:
    """Reubica importes sintéticos en un sobre de control; no es un XTX para presentar."""
    ns = "http://xml.e-tax.nta.go.jp/XSD/shotoku"
    xsd_ns = {"x": "http://www.w3.org/2001/XMLSchema"}
    root = _empty_control()
    page = root.find(f".//{{{ns}}}KOA020-1")
    if page is None:
        raise ValueError("El control sintético no contiene KOA020-1")
    body = etree.SubElement(page, f"{{{ns}}}ABB00000")
    legacy = etree.fromstring(payload)
    values = {el.tag: el.text for el in legacy.xpath(".//ABB00000/*")}
    schema = etree.parse(str(form_xsd))
    nodes = schema.xpath(
        '//x:complexType[@name="KOA020-1-23-0type"]//x:element[starts-with(@name,"ABB")]',
        namespaces=xsd_ns,
    )
    groups: dict[tuple[str, ...], etree._Element] = {("ABB00000",): body}
    mapped = 0
    for node in nodes:
        tag = node.get("name")
        if tag not in values:
            continue
        parents = node.xpath("ancestor::x:element/@name", namespaces=xsd_ns)
        path = tuple(part for part in parents if part.startswith("ABB")) + (tag,)
        parent = body
        for index, part in enumerate(path[1:], start=1):
            key = path[: index + 1]
            if key not in groups:
                groups[key] = etree.SubElement(parent, f"{{{ns}}}{part}")
            parent = groups[key]
        parent.text = values[tag]
        mapped += 1
    return root, mapped, len(values)


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "Uso: python ../tools/verify_official_xtx.py RUTA/RKO0010-250.xsd",
            file=sys.stderr,
        )
        return 2
    schema = etree.XMLSchema(etree.parse(str(Path(sys.argv[1]))))
    control_ok = schema.validate(_empty_control())
    print("Control sintetico vacio:", "PASS" if control_ok else "FAIL")
    if not control_ok:
        for issue in schema.error_log:
            print(issue.message)
        return 2
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with get_session_factory(engine)() as session:
            seed_demo_data(session)
            payload = build_xtx(build_filing_draft(session, 2025))
        mapped_control, count, total = _mapped_control(
            payload, Path(sys.argv[1]).with_name("KOA020-023.xsd")
        )
        mapped_ok = schema.validate(mapped_control)
        print(
            f"Control con importes sinteticos: {count}/{total}; XSD:",
            "PASS" if mapped_ok else "FAIL",
        )
        if not mapped_ok:
            for issue in schema.error_log:
                print(issue.message)
        # Valores artificiales en todas las constantes ABB usadas por el generador.
        # Una prueba estructural no valida la semántica ni las reglas tributarias.
        all_tags = sorted(
            {
                value
                for key, value in vars(fields).items()
                if key.startswith("TAG_") and isinstance(value, str) and value.startswith("ABB")
            }
        )
        all_legacy = etree.Element("DATA")
        all_body = etree.SubElement(all_legacy, "ABB00000")
        for tag in all_tags:
            etree.SubElement(all_body, tag).text = "100000"
        all_control, all_count, all_total = _mapped_control(
            etree.tostring(all_legacy), Path(sys.argv[1]).with_name("KOA020-023.xsd")
        )
        all_ok = all_count == all_total and schema.validate(all_control)
        print(
            f"Control de todas las constantes ABB: {all_count}/{all_total}; XSD:",
            "PASS" if all_ok else "FAIL",
        )
        if not all_ok:
            for issue in schema.error_log:
                print(issue.message)
            return 2
        # Segunda pagina: un pagador y retencion, datos exclusivamente sinteticos.
        second = _empty_control()
        ns = "http://xml.e-tax.nta.go.jp/XSD/shotoku"
        form = second.find(f".//{{{ns}}}KOA020")
        if form is None:
            raise ValueError("Falta KOA020 en el control")
        page2 = etree.SubElement(form, f"{{{ns}}}KOA020-2")
        breakdown = etree.SubElement(page2, f"{{{ns}}}ABD00000")
        payer = etree.SubElement(breakdown, f"{{{ns}}}ABD00010")
        for tag, value in (
            ("ABD00040", "Synthetic Payer"),
            ("ABD00050", "3000000"),
            ("ABD00060", "100000"),
        ):
            etree.SubElement(payer, f"{{{ns}}}{tag}").text = value
        etree.SubElement(breakdown, f"{{{ns}}}ABD00070").text = "100000"
        second_ok = schema.validate(second)
        print(
            "Control sintetico de pagador en segunda pagina; XSD:", "PASS" if second_ok else "FAIL"
        )
        if not second_ok:
            for issue in schema.error_log:
                print(issue.message)
            return 2
        print("AVISO: controles estructurales sinteticos; no son documentos presentables.")
        valid = schema.validate(etree.fromstring(payload))
        print("XSD oficial del generador actual:", "PASS" if valid else "FAIL")
        for issue in schema.error_log:
            print(issue.message)
        return 0 if valid else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
