"""Comprueba el generador real R7 con datos sintéticos y los XSD oficiales locales.

Requiere lxml y el árbol completo de e-tax19.CAB. No abre la base local.
Una validación XSD correcta no acredita aptitud fiscal ni aceptación por e-Tax.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from lxml import etree

from app.db.session import create_db_engine, get_session_factory
from app.models import Base
from app.seed.dev_seed import seed_demo_data
from app.services.forms import etax_schema_r7 as fields
from app.services.forms.drafting import build_filing_draft
from app.services.forms.tax_office import resolve_tax_office
from app.services.forms.xtx_document import (
    PayerIncome,
    PremiumPayment,
    XtxDetails,
    build_xtx_document,
)
from app.services.forms.xtx_envelope import XtxIdentity


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("schema", type=Path)
    cli.add_argument(
        "--output", type=Path, help="Guardar el ejemplo sintético; no sobrescribe archivos."
    )
    args = cli.parse_args()
    path = args.schema.resolve()
    if path.name != "RKO0010-250.xsd":
        raise ValueError("Se requiere el esquema del procedimiento RKO0010-250.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    schema = etree.XMLSchema(etree.parse(str(path), parser))
    catalog_path = (
        Path(__file__).resolve().parents[1] / "backend/app/services/forms/xtx_fields_r7.json"
    )
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    ns = {"x": "http://www.w3.org/2001/XMLSchema"}
    definitions = 0
    for filename, form in catalog["forms"].items():
        source = path.with_name(filename)
        if hashlib.sha256(source.read_bytes()).hexdigest() != form["sha256"]:
            raise ValueError("El XSD local cambió respecto al catálogo: " + filename)
        doc = etree.parse(str(source), parser)
        for page, rows in form["pages"].items():
            version = "23-0" if page.startswith("KOA020") else "11-0"
            types = doc.xpath(
                "//x:complexType[@name=$name]", name=f"{page}-{version}type", namespaces=ns
            )
            if len(types) != 1:
                raise ValueError("Página no encontrada: " + page)
            actual = []
            for element in types[0].xpath(".//x:element", namespaces=ns):
                parents = element.xpath("ancestor::x:element/@name", namespaces=ns)
                annotation = element.xpath("./x:annotation/x:appinfo/text()", namespaces=ns)
                actual.append(
                    {
                        "path": "/".join([*parents, element.get("name")]),
                        "type": element.get("type"),
                        "label": "".join(annotation).strip('"'),
                        "max": element.get("maxOccurs", "1"),
                    }
                )
            if rows != actual:
                raise ValueError(
                    "El catálogo difiere de las rutas, tipos o etiquetas oficiales: " + page
                )
            definitions += len(rows)
    print(f"Catalogo oficial: {definitions} definiciones verificadas; PASS")
    offices = etree.parse(str(path.parent.parent / "general/zeimusho.xsd"), parser)
    office = resolve_tax_office("tsushima")
    official_offices = "".join(offices.getroot().itertext()).splitlines()
    if f"{office.etax_code}:{office.header_name}" not in official_offices:
        raise ValueError("La oficina configurada no coincide con la tabla oficial.")
    print("Oficina fiscal contrastada con zeimusho.xsd: PASS")
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with get_session_factory(engine)() as db:
            seed_demo_data(db)
            draft = build_filing_draft(db, 2025)
            assert draft.taxpayer_profile is not None
            assert draft.taxpayer_profile.address is not None
            identity = XtxIdentity(
                "0000000000000000",
                draft.taxpayer_name,
                draft.taxpayer_profile.address,
                "06127",
                "000000000000",
                date(1980, 1, 1),
            )
            # Distribución artificial expresamente definida para esta prueba.
            details = XtxDetails(
                payers=(
                    PayerIncome(
                        "jigyo",
                        "Synthetic Customer",
                        "Synthetic Address",
                        draft.sales_revenue,
                        draft.tax.withholding_tax,
                    ),
                ),
                monthly_sales=(draft.sales_revenue, *([0] * 11)),
                opening_balances={},
                business_period=(date(2025, 1, 1), date(2025, 12, 31)),
                premiums=(
                    PremiumPayment(
                        "social",
                        "社会保険料",
                        draft.tax.deduction_breakdown.social_insurance,
                        draft.tax.deduction_breakdown.social_insurance,
                    ),
                    PremiumPayment(
                        "ideco",
                        "個人型確定拠出年金",
                        draft.tax.deduction_breakdown.ideco,
                        draft.tax.deduction_breakdown.ideco,
                    ),
                ),
            )
            result = build_xtx_document(
                draft, identity, created_on=date(2026, 1, 1), details=details
            )
        document = etree.fromstring(result.xml, parser)
        valid = schema.validate(document)
        print("XSD oficial del generador real:", "PASS" if valid else "FAIL")
        for issue in schema.error_log:
            print(issue.message)
        # Comprobar referencias aparte: el RDF es lax en el XSD.
        ids = {
            value
            for element in document.iter()
            for key, value in element.attrib.items()
            if key in {"id", "ID"}
        }
        refs = [element.get("IDREF") for element in document.iter() if element.get("IDREF")]
        rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        refs += [
            element.get("about")[1:]
            for element in document.iter(f"{{{rdf}}}Description")
            if element.get("about", "").startswith("#")
        ]
        refs_ok = all(ref in ids for ref in refs)
        print("Referencias IT y RDF:", "PASS" if refs_ok else "FAIL")
        print("Preparado para presentar:", result.ready_for_submission)
        print("Requisitos pendientes:", ", ".join(result.missing))
        # Prueba estructural independiente de todas las constantes monetarias ABB.
        import xml.etree.ElementTree as std_et

        from app.services.forms.xtx_catalog import emit_fields
        from app.services.forms.xtx_envelope import SHOTOKU, build_experimental_envelope

        control, page = build_experimental_envelope(
            identity, created_by="Synthetic", created_on=date(2026, 1, 1)
        )
        amounts = {
            value: 100000
            for key, value in vars(fields).items()
            if key.startswith("TAG_") and isinstance(value, str) and value.startswith("ABB")
        }
        emit_fields(page, "KOA020-1", amounts)
        coverage_ok = schema.validate(etree.fromstring(std_et.tostring(control), parser))
        emitted = sum(1 for el in control.iter() if el.tag.split("}")[-1] in amounts)
        print(
            f"Constantes monetarias: {emitted}/{len(amounts)}; XSD:",
            "PASS" if coverage_ok else "FAIL",
        )
        assert page.tag == f"{{{SHOTOKU}}}KOA020-1"
        passed = valid and refs_ok and coverage_ok and emitted == len(amounts)
        if passed and args.output:
            with args.output.open("xb") as output:
                output.write(result.xml)
            print("Guardado ejemplo exclusivamente sintético (no apto para presentar).")
        return 0 if passed else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
