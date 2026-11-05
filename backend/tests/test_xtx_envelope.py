"""Pruebas sintéticas del sobre experimental; no certifican presentación."""

import xml.etree.ElementTree as ET  # nosec B405
from datetime import date

import pytest

from app.services.forms.xtx_envelope import RDF, SHOTOKU, XtxIdentity, build_experimental_envelope


def test_envelope_has_resolvable_rdf_and_transient_identity() -> None:
    identity = XtxIdentity("1234567890123456", "Synthetic Person", "Example Street", "01143")
    assert identity.user_id not in repr(identity)
    assert identity.name not in repr(identity)
    assert identity.address not in repr(identity)
    root, page = build_experimental_envelope(
        identity, created_by="Synthetic", created_on=date(2026, 1, 1)
    )
    refs = root.findall(f".//{{{RDF}}}Description[@about]")
    ids = {element.get("id") for element in root.iter()}
    assert {ref.get("about") for ref in refs} == {"#IT", "#KOA020-1"}
    assert all(ref.get("about", "")[1:] in ids for ref in refs)
    assert root.find(f".//{{{SHOTOKU}}}NOZEISHA_ID").text == identity.user_id
    assert page.tag == f"{{{SHOTOKU}}}KOA020-1"
    assert ET.tostring(root).count(identity.user_id.encode()) == 1


@pytest.mark.parametrize(
    "user_id", ["", "123", "１２３４５６７８９０１２３４５６", "123456789012345a"]
)
def test_rejects_missing_or_invalid_user_id(user_id: str) -> None:
    with pytest.raises(ValueError, match="16"):
        build_experimental_envelope(
            XtxIdentity(user_id, "Synthetic", "Example", "01143"),
            created_by="Synthetic",
            created_on=date(2026, 1, 1),
        )


def test_rejects_missing_identity_fields() -> None:
    with pytest.raises(ValueError):
        build_experimental_envelope(
            XtxIdentity("1234567890123456", "", "Example", "01143"),
            created_by="Synthetic",
            created_on=date(2026, 1, 1),
        )
