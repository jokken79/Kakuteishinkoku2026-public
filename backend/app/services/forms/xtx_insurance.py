"""Primas netas del certificado y cálculo R7; nunca confundir pago con 控除."""

from dataclasses import dataclass
from typing import Literal

InsuranceCategory = Literal[
    "new_life", "old_life", "care", "new_pension", "old_pension", "earthquake", "old_damage"
]


@dataclass(frozen=True)
class InsurancePayment:
    category: InsuranceCategory
    paid: int
    outside_year_end_adjustment: int


def new_contract(paid: int) -> int:
    """NTA 1140, R7: redondeo de la fracción de yen hacia arriba."""
    if paid <= 20_000:
        return paid
    if paid <= 40_000:
        return (paid + 1) // 2 + 10_000
    return min(40_000, (paid + 3) // 4 + 20_000)


def old_contract(paid: int) -> int:
    if paid <= 25_000:
        return paid
    if paid <= 50_000:
        return (paid + 1) // 2 + 12_500
    return min(50_000, (paid + 3) // 4 + 25_000)


def insurance_deductions(rows: tuple[InsurancePayment, ...]) -> tuple[int, int]:
    """NTA 1140/1145. No aplica la ampliación de 新生命保険料 de R8."""
    amounts: dict[str, int] = {}
    for row in rows:
        if not 0 <= row.outside_year_end_adjustment <= row.paid:
            raise ValueError("Primas incompatibles con el ajuste de fin de año.")
        amounts[row.category] = amounts.get(row.category, 0) + row.paid

    def group(new: str, old: str) -> int:
        old_value = old_contract(amounts.get(old, 0))
        combined = min(40_000, new_contract(amounts.get(new, 0)) + old_value)
        return max(old_value, combined)

    life = min(120_000, group("new_life", "old_life")
               + group("new_pension", "old_pension") + new_contract(amounts.get("care", 0)))
    old_damage = amounts.get("old_damage", 0)
    old_deduction = old_damage if old_damage <= 10_000 else min(
        15_000, (old_damage + 1) // 2 + 5_000
    )
    earthquake = min(50_000, amounts.get("earthquake", 0) + old_deduction)
    return life, earthquake


INSURANCE_TAGS: dict[str, tuple[str, str]] = {
    "new_life": ("ABH00215", "ABH00217"),
    "old_life": ("ABH00220", "ABH00222"),
    "new_pension": ("ABH00225", "ABH00227"),
    "old_pension": ("ABH00230", "ABH00232"),
    "care": ("ABH00235", "ABH00237"),
    "earthquake": ("ABH00250", "ABH00255"),
    "old_damage": ("ABH00260", "ABH00265"),
}
