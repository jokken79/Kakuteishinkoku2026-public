"""Comprueba el XML heredado con datos sintéticos contra el XSD oficial local.

Uso desde backend: python ../tools/verify_official_xtx.py RUTA/RKO0010-250.xsd
Requiere lxml y el árbol completo del CAB oficial descomprimido. Nunca abre la BD local.
"""

from __future__ import annotations

import sys
from pathlib import Path

# El proyecto aislado debe preceder cualquier instalación editable del equipo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db.session import create_db_engine, get_session_factory
from app.models import Base
from app.seed.dev_seed import seed_demo_data
from app.services.forms.drafting import build_filing_draft
from app.services.forms.etax_export import build_xtx
from lxml import etree


def _empty_control() -> etree._Element:
    """Control sintético sin importes: demuestra que el esquema se carga."""
    ns = "http://xml.e-tax.nta.go.jp/XSD/shotoku"
    gen = "http://xml.e-tax.nta.go.jp/XSD/general"
    rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    root = etree.Element(f"{{{ns}}}DATA", nsmap={None: ns, "gen": gen, "rdf": rdf})

    def child(parent: etree._Element, name: str, **attrs: str) -> etree._Element:
        return etree.SubElement(parent, f"{{{ns}}}{name}", **attrs)

    procedure = child(root, "RKO0010", id="proc", VR="25.0.0")
    catalog = child(procedure, "CATALOG", id="catalog")
    etree.SubElement(catalog, f"{{{rdf}}}RDF")
    contents = child(procedure, "CONTENTS", id="contents")
    it = child(contents, "IT", id="identity", VR="1.5")
    office = child(it, "ZEIMUSHO", ID="ZEIMUSHO")
    etree.SubElement(office, f"{{{gen}}}zeimusho_CD").text = "01143"
    child(it, "NOZEISHA_ID", ID="NOZEISHA_ID").text = "0000000000000000"
    child(it, "NOZEISHA_NM", ID="NOZEISHA_NM").text = "架空 太郎"
    child(it, "NOZEISHA_ADR", ID="NOZEISHA_ADR").text = "架空住所"
    child(child(it, "TETSUZUKI", ID="TETSUZUKI"), "procedure_CD").text = "RKO0010"
    form = child(contents, "KOA020", VR="23.0", softNM="test",
                 sakuseiNM="test", sakuseiDay="2026-01-01")
    child(form, "KOA020-1")
    return root


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python ../tools/verify_official_xtx.py RUTA/RKO0010-250.xsd", file=sys.stderr)
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
        valid = schema.validate(etree.fromstring(payload))
        print("XSD oficial:", "PASS" if valid else "FAIL")
        for issue in schema.error_log:
            print(issue.message)
        return 0 if valid else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
