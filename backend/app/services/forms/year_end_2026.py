"""Estampado parcial del 扶養控除等申告書 oficial de 2026 para revisión."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.forms.overlay import Field, render_overlay


def _fit(text: str, max_width: float, preferred_size: float) -> float:
    """Limita el ancho incluso si todos los caracteres son de ancho completo."""
    return min(preferred_size, max_width / max(len(text), 1))


def _birth_fields(value: date) -> list[Field]:
    # El formulario usa era japonesa. Las fechas anteriores a Meiji quedan sin estampar.
    eras = (
        (date(2019, 5, 1), 2018, (274, 233)),
        (date(1989, 1, 8), 1988, (269, 233)),
        (date(1926, 12, 25), 1925, (258, 233)),
        (date(1912, 7, 30), 1911, (269, 227)),
        (date(1868, 1, 25), 1867, (258, 227)),
    )
    for start, offset, circle in eras:
        if value >= start:
            return [
                Field("○", circle[0], circle[1], align="c", size=7),
                Field(str(value.year - offset), 282, 233, align="l", size=8),
                Field(f"{value.month:02d}", 308, 233, align="l", size=8),
                Field(f"{value.day:02d}", 334, 233, align="l", size=8),
            ]
    return []


def render_year_end_2026(data: dict[str, Any]) -> bytes:
    """Produce un PDF marcado como borrador; no acredita elegibilidad fiscal."""
    fields = [
        Field("確認用・提出前に確認", 30, 19, align="l", size=8),
        Field(data["employer_name"], 170, 55, align="l",
              size=_fit(data["employer_name"], 155, 7)),
        Field(data["taxpayer_kana"], 387, 43, align="l",
              size=_fit(data["taxpayer_kana"], 145, 7)),
        Field(data["taxpayer_name"], 387, 60, align="l",
              size=_fit(data["taxpayer_name"], 145, 9)),
    ]
    taxpayer_address = data["taxpayer_address"]
    for index in range(0, len(taxpayer_address), 33):
        fields.append(Field(taxpayer_address[index : index + 33], 385,
                            106 + index // 33 * 7, align="l", size=6))
    dep = data.get("dependent")
    if dep:
        fields.extend(
            [
                Field(dep["name_kana"], 110, 207, align="l",
                      size=_fit(dep["name_kana"], 90, 7)),
                Field(dep["name"], 110, 231, align="l", size=_fit(dep["name"], 90, 9)),
                Field(dep["relationship"], 205, 234, align="l",
                      size=_fit(dep["relationship"], 45, 7)),
            ]
        )
        address = dep["address"]
        for index in range(0, len(address), 17):
            fields.append(Field(address[index : index + 17], 579, 211 + index // 17 * 8,
                                align="l", size=6))
        if dep["birth_date"]:
            fields.extend(_birth_fields(dep["birth_date"]))
        if dep["income_estimate"] is not None:
            fields.append(Field(str(dep["income_estimate"]), 454, 233, align="r", size=8))
        if dep["elderly_other"]:
            fields.append(Field("×", 362, 216, align="c", size=7))
    if data["disability"] == "ordinary":
        fields.extend(
            [
                Field("×", 106.5, 370, align="c", size=8),
                Field("○", 207, 384, align="c", size=9),
                Field(data["disability_details"], 358, 383, align="l",
                      size=_fit(data["disability_details"], 320, 7)),
            ]
        )
    return render_overlay("r08_fuyo.pdf", {0: fields})
