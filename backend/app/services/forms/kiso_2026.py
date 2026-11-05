"""Borrador parcial sobre el 基礎控除申告書 oficial de 国税庁 de 2026."""

from __future__ import annotations

from typing import Any

from app.services.forms.overlay import Field, render_overlay
from app.services.tax_rules import load_tax_rules


def _fit(text: str, width: float, preferred: float) -> float:
    return min(preferred, width / max(len(text), 1))


def render_kiso_2026(data: dict[str, Any], salary_income_amount: int | None) -> bytes:
    """Rellena solo datos expresos; el resto queda para revisión manual."""
    fields = [
        Field("確認用・提出前に確認", 30, 19, align="l", size=8),
        Field(data["employer_name"], 186, 52, align="l",
              size=_fit(data["employer_name"], 165, 6)),
        Field(data["taxpayer_kana"], 414, 47, align="l",
              size=_fit(data["taxpayer_kana"], 235, 6)),
        Field(data["taxpayer_name"], 414, 69, align="l",
              size=_fit(data["taxpayer_name"], 235, 8)),
    ]
    address = data["taxpayer_address"]
    for index in range(0, len(address), 36):
        fields.append(Field(address[index:index + 36], 414, 84 + index // 36 * 7,
                            align="l", size=6))
    if salary_income_amount is not None:
        fields.extend([
            Field(str(data["salary_revenue"]), 205, 159, align="r", size=8),
            Field(str(salary_income_amount), 299, 159, align="r", size=8),
        ])
    if data["complete_income_estimate"] and salary_income_amount is not None:
        total = salary_income_amount + data["other_income"]
        fields.extend([
            Field(str(data["other_income"]), 299, 186, align="r", size=8),
            Field(str(total), 299, 207, align="r", size=8),
        ])
        limits = (4_890_000, 6_550_000, 9_000_000, 9_500_000, 10_000_000,
                  23_500_000, 24_000_000, 24_500_000, 25_000_000)
        for index, limit in enumerate(limits):
            if total <= limit:
                fields.append(Field("×", 85, 235 + index * 13.6, align="c", size=8))
                fields.append(Field(str(load_tax_rules(2026).kiso_kojo_for(total)),
                                    299, 304, align="r", size=8))
                break
    return render_overlay("r08_kiso.pdf", {0: fields})
