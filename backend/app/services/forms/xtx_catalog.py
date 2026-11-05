"""Rutas y orden extraídos del XSD oficial, independientes de datos personales."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET  # nosec B405
from functools import lru_cache
from pathlib import Path
from typing import TypedDict, cast

from app.services.forms.xtx_envelope import SHOTOKU


class FieldDefinition(TypedDict):
    path: str
    type: str | None
    label: str
    max: str


@lru_cache(maxsize=1)
def field_catalog() -> dict[str, list[FieldDefinition]]:
    raw = json.loads(Path(__file__).with_name("xtx_fields_r7.json").read_text(encoding="utf-8"))
    return {
        page: cast(list[FieldDefinition], rows)
        for form in raw["forms"].values()
        for page, rows in form["pages"].items()
    }


def emit_fields(parent: ET.Element, page: str, values: dict[str, int | str | ET.Element]) -> None:
    """Emite campos conocidos en orden oficial; rechaza omisiones por tag desconocido."""
    rows = field_catalog()[page]
    definitions = {row["path"].split("/")[-1]: row for row in rows if row["type"]}
    unknown = set(values) - definitions.keys()
    if unknown:
        raise ValueError("Campos sin correspondencia en el XSD: " + ", ".join(sorted(unknown)))
    groups: dict[str, ET.Element] = {"": parent}
    for row in rows:
        tag = row["path"].split("/")[-1]
        if not row["type"] or tag not in values:
            continue
        parts = row["path"].split("/")
        for index, part in enumerate(parts[:-1]):
            path = "/".join(parts[: index + 1])
            if path not in groups:
                groups[path] = ET.SubElement(
                    groups["/".join(parts[:index])], f"{{{SHOTOKU}}}{part}"
                )
        holder = groups["/".join(parts[:-1])]
        value = values[tag]
        if isinstance(value, ET.Element):
            if value.tag != f"{{{SHOTOKU}}}{tag}":
                raise ValueError("El campo compuesto no coincide con su definición.")
            holder.append(value)
        else:
            ET.SubElement(holder, f"{{{SHOTOKU}}}{tag}").text = str(value)
