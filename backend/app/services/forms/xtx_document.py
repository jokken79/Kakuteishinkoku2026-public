"""Generador estructural R7 con trazabilidad de omisiones; descarga aún protegida."""

from __future__ import annotations

import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.services.forms.drafting import FilingDraftResult
from app.services.forms.xtx_catalog import emit_fields
from app.services.forms.xtx_envelope import (
    GENERAL,
    RDF,
    SHOTOKU,
    XtxIdentity,
    build_experimental_envelope,
)
from app.services.forms.xtx_insurance import (
    INSURANCE_TAGS,
    InsurancePayment,
    insurance_deductions,
)


@dataclass(frozen=True)
class PayerIncome:
    kind: Literal["jigyo", "kyuyo"]
    name: str = field(repr=False)
    location: str = field(repr=False)
    gross: int
    withholding: int


@dataclass(frozen=True)
class PremiumPayment:
    category: Literal["social", "ideco"]
    label: str
    paid: int
    outside_year_end_adjustment: int


@dataclass(frozen=True)
class MunicipalDonation:
    name: str = field(repr=False)
    location: str = field(repr=False)
    paid: int


@dataclass(frozen=True)
class XtxDetails:
    payers: tuple[PayerIncome, ...] = ()
    monthly_sales: tuple[int, ...] | None = None
    opening_balances: dict[str, int] | None = field(default=None, repr=False)
    premiums: tuple[PremiumPayment, ...] = ()
    business_period: tuple[date, date] | None = None
    insurance: tuple[InsurancePayment, ...] = ()
    separate_damage_contracts: bool = False
    donations: tuple[MunicipalDonation, ...] = ()


@dataclass(frozen=True)
class XtxBuild:
    xml: bytes = field(repr=False)
    missing: tuple[str, ...]
    mapped_tags: tuple[str, ...]

    @property
    def ready_for_submission(self) -> bool:
        # El visor reconoce el XML base; falta cotejar casillas y escenarios fiscales.
        return False


def _amount(values: dict[str, int | str | ET.Element], tag: str) -> int:
    value = values.get(tag, 0)
    if not isinstance(value, int):
        raise ValueError("La casilla monetaria contiene un valor no numérico: " + tag)
    return value


def _reference(tag: str, target: str) -> ET.Element:
    return ET.Element(f"{{{SHOTOKU}}}{tag}", {"IDREF": target})


def _value(tag: str, kind: str, value: str) -> ET.Element:
    node = ET.Element(f"{{{SHOTOKU}}}{tag}")
    ET.SubElement(node, f"{{{SHOTOKU}}}{kind}").text = value
    return node


def _date_value(tag: str, value: date) -> ET.Element:
    node = ET.Element(f"{{{SHOTOKU}}}{tag}")
    for name, text in (
        ("era", "5"),
        ("yy", str(value.year - 2018)),
        ("mm", str(value.month)),
        ("dd", str(value.day)),
    ):
        ET.SubElement(node, f"{{{GENERAL}}}{name}").text = text
    return node


def _month_day(tag: str, value: date) -> ET.Element:
    node = ET.Element(f"{{{SHOTOKU}}}{tag}")
    ET.SubElement(node, f"{{{GENERAL}}}mm").text = str(value.month)
    ET.SubElement(node, f"{{{GENERAL}}}dd").text = str(value.day)
    return node


def _page2(form: ET.Element, details: XtxDetails, missing: list[str]) -> None:
    rows = details.payers
    # KOA020-2 permite cuatro pagadores por página; se repite la página.
    for start in range(0, max(1, len(rows)), 4):
        page = ET.SubElement(form, f"{{{SHOTOKU}}}KOA020-2")
        emit_fields(
            page,
            "KOA020-2",
            {
                "ABC00010": _reference("ABC00010", "NENBUN"),
                "ABC00015": _reference("ABC00015", "SHINKOKU_KBN"),
                "ABC00040": _reference("ABC00040", "NOZEISHA_ADR"),
                "ABC00070": _reference("ABC00070", "NOZEISHA_NM"),
            },
        )
        if not rows:
            missing.append("income_payers")
            continue
        group = ET.SubElement(page, f"{{{SHOTOKU}}}ABD00000")
        for row in rows[start : start + 4]:
            if row.gross < 0 or row.withholding < 0 or row.withholding > row.gross:
                raise ValueError("Importes de pagador incompatibles.")
            if not row.name.strip() or not row.location.strip():
                raise ValueError("Cada pagador requiere nombre y localización.")
            item = ET.SubElement(group, f"{{{SHOTOKU}}}ABD00010")
            for tag, value in (
                ("ABD00020", "営業等" if row.kind == "jigyo" else "給与"),
                ("ABD00030", row.location),
                ("ABD00040", row.name),
                ("ABD00050", str(row.gross)),
                ("ABD00060", str(row.withholding)),
            ):
                ET.SubElement(item, f"{{{SHOTOKU}}}{tag}").text = value
        # La suma global figura en la última página, evitando duplicar retenciones.
        if start + 4 >= len(rows):
            ET.SubElement(group, f"{{{SHOTOKU}}}ABD00070").text = str(
                sum(r.withholding for r in rows)
            )


_EXPENSE_TAGS = {
    "租税公課": "AMF00190",
    "荷造運賃": "AMF00200",
    "水道光熱費": "AMF00210",
    "旅費交通費": "AMF00220",
    "通信費": "AMF00230",
    "広告宣伝費": "AMF00240",
    "接待交際費": "AMF00250",
    "損害保険料": "AMF00260",
    "修繕費": "AMF00270",
    "消耗品費": "AMF00280",
    "減価償却費": "AMF00290",
    "福利厚生費": "AMF00300",
    "給料賃金": "AMF00310",
    "外注工賃": "AMF00320",
    "利子割引料": "AMF00330",
    "地代家賃": "AMF00340",
    "貸倒金": "AMF00350",
    "雑費": "AMF00370",
}
_ASSETS = {
    "現金": "AMG00260",
    "当座預金": "AMG00270",
    "定期預金": "AMG00280",
    "普通預金": "AMG00290",
    "その他の預金": "AMG00290",
    "受取手形": "AMG00300",
    "売掛金": "AMG00310",
    "有価証券": "AMG00320",
    "棚卸資産": "AMG00330",
    "前払金": "AMG00340",
    "貸付金": "AMG00350",
    "建物": "AMG00360",
    "建物附属設備": "AMG00370",
    "機械装置": "AMG00380",
    "車両運搬具": "AMG00390",
    "工具器具備品": "AMG00400",
    "土地": "AMG00410",
    "事業主貸": "AMG00430",
}
_LIABILITIES = {
    "支払手形": "AMG00640",
    "買掛金": "AMG00650",
    "借入金": "AMG00660",
    "未払金": "AMG00670",
    "前受金": "AMG00680",
    "預り金": "AMG00690",
    "貸倒引当金": "AMG00710",
    "事業主借": "AMG00730",
    "元入金": "AMG00740",
}


def _annex(
    contents: ET.Element,
    draft: FilingDraftResult,
    details: XtxDetails,
    created_on: date,
    missing: list[str],
) -> None:
    if draft.filing_type == "shiroiro":
        missing.append("shiroiro_annex")
        return
    form = ET.SubElement(
        contents,
        f"{{{SHOTOKU}}}KOA210",
        {
            "id": "KOA210-1",
            "VR": "11.0",
            "softNM": "Kakuteishinkoku",
            "sakuseiNM": draft.taxpayer_name,
            "sakuseiDay": created_on.isoformat(),
        },
    )
    page = ET.SubElement(form, f"{{{SHOTOKU}}}KOA210-1")
    pl = draft.income_statement
    amounts: dict[str, int | str | ET.Element] = {
        "AMA00000": _reference("AMA00000", "NENBUN"),
        "AMF00100": pl.total_revenue,
        "AMF00170": pl.total_revenue,
        "AMF00380": pl.total_expense,
        "AMF00390": pl.net_income,
        "AMF00500": pl.net_income,
        "AMF00510": draft.aoiro_deduction,
        "AMF00530": draft.business_income,
    }
    additional: list[tuple[str, int]] = []
    profile = draft.taxpayer_profile
    assert profile is not None
    amounts["AMB00010"] = profile.address or ""
    amounts["AMB00040"] = _reference("AMB00040", "NOZEISHA_NM")
    if profile.name_kana:
        amounts["AMB00030"] = _reference("AMB00030", "NOZEISHA_NM_KN")
    if profile.occupation:
        amounts["AMB00090"] = _reference("AMB00090", "SHOKUGYO")
    period = details.business_period
    if period is None:
        missing.append("business_period")
    else:
        start, end = period
        if not start <= end or start.year != draft.year or end.year != draft.year:
            raise ValueError("El período de actividad no pertenece al ejercicio.")
        amounts["AMF00030"] = _month_day("AMF00030", start)
        amounts["AMF00040"] = _month_day("AMF00040", end)
        if start != date(draft.year, 1, 1) or end != date(draft.year, 12, 31):
            missing.append("business_period_reconciliation")
    for line in pl.expenses:
        tag = _EXPENSE_TAGS.get(line.account_name)
        if tag is None:
            # No se transforma una cuenta desconocida en 雑費 por conveniencia.
            additional.append((line.account_name, line.amount))
            continue
        amounts[tag] = _amount(amounts, tag) + line.amount
        if tag in {"AMF00290", "AMF00310", "AMF00330", "AMF00340"} and line.amount:
            missing.append("expense_schedule:" + tag)
    emit_fields(page, "KOA210-1", amounts)
    expense_group = page.find(f".//{{{SHOTOKU}}}AMF00180")
    assert expense_group is not None
    if len(additional) > 6:
        raise ValueError("El formulario admite como máximo seis cuentas de gasto adicionales.")
    insert_at = next(
        (
            i
            for i, el in enumerate(expense_group)
            if el.tag.split("}")[-1] in {"AMF00370", "AMF00380"}
        ),
        len(expense_group),
    )
    for offset, (name, amount) in enumerate(additional):
        row = ET.Element(f"{{{SHOTOKU}}}AMF00355")
        ET.SubElement(row, f"{{{SHOTOKU}}}AMF00060").text = name
        ET.SubElement(row, f"{{{SHOTOKU}}}AMF00360").text = str(amount)
        expense_group.insert(insert_at + offset, row)
    page2 = ET.SubElement(form, f"{{{SHOTOKU}}}KOA210-2")
    months = details.monthly_sales
    sales: dict[str, int | str | ET.Element] = {
        "AMF00538": _reference("AMF00538", "NENBUN"),
        "AMF00980": draft.sales_revenue,
        "AMF01520": pl.net_income,
    }
    sales["AMF00560"] = _reference("AMF00560", "NOZEISHA_NM")
    if profile.name_kana:
        sales["AMF00550"] = _reference("AMF00550", "NOZEISHA_NM_KN")
    if months is None:
        missing.append("monthly_sales")
    elif len(months) != 12 or any(type(n) is not int or n < 0 for n in months):
        raise ValueError("El desglose mensual debe contener doce importes no negativos.")
    elif sum(months) != draft.sales_revenue:
        raise ValueError("El desglose mensual no coincide con el ingreso anual.")
    else:
        for index, amount in enumerate(months):
            sales[f"AMF{600 + index * 30:05d}"] = amount
    deduction_tag = "AMF01550" if draft.filing_type in {"aoiro_65", "aoiro_55"} else "AMF01580"
    sales[deduction_tag] = draft.aoiro_deduction
    emit_fields(page2, "KOA210-2", sales)
    page3 = ET.SubElement(form, f"{{{SHOTOKU}}}KOA210-3")
    emit_fields(page3, "KOA210-3", {"AMF02310": draft.sales_revenue})
    customer_group = page3.find(f"{{{SHOTOKU}}}AMF02220")
    assert customer_group is not None
    customers = [p for p in details.payers if p.kind == "jigyo"]
    if sum(p.gross for p in customers) != draft.sales_revenue:
        missing.append("sales_customer_schedule")
    # Se detallan los cuatro principales y se suma el resto en la casilla oficial.
    customers = sorted(customers, key=lambda p: p.gross, reverse=True)
    for index, payer in enumerate(customers[:4]):
        row = ET.Element(f"{{{SHOTOKU}}}AMF02230")
        for tag, value in (
            ("AMF02240", payer.name),
            ("AMF02250", payer.location),
            ("AMF02290", str(payer.gross)),
        ):
            ET.SubElement(row, f"{{{SHOTOKU}}}{tag}").text = value
        customer_group.insert(index, row)
    if len(customers) > 4:
        other = ET.Element(f"{{{SHOTOKU}}}AMF02300")
        other.text = str(sum(p.gross for p in customers[4:]))
        customer_group.insert(4, other)
    page4 = ET.SubElement(form, f"{{{SHOTOKU}}}KOA210-4")
    bs = draft.balance_sheet
    balance: dict[str, int | str | ET.Element] = {
        "AMG00750": bs.net_income,
    }
    if period is not None:
        start, end = period
        balance["AMG00010"] = _date_value("AMG00010", end)
        for tag in ("AMG00050", "AMG00500"):
            balance[tag] = _month_day(tag, start)
        for tag in ("AMG00250", "AMG00630"):
            balance[tag] = _month_day(tag, end)
    for bs_line in [*bs.assets, *bs.liabilities, *bs.equity]:
        tag = _ASSETS.get(bs_line.account_name) or _LIABILITIES.get(bs_line.account_name)
        if tag is None:
            missing.append("balance_account:" + bs_line.account_code)
            continue
        amount = -bs_line.amount if bs_line in bs.equity and tag == "AMG00430" else bs_line.amount
        balance[tag] = _amount(balance, tag) + amount
    # No se usan totales del balance interno sin reconciliar la reclasificación fiscal.
    balance["AMG00440"] = sum(_amount(balance, tag) for tag in set(_ASSETS.values()))
    balance["AMG00760"] = (
        sum(_amount(balance, tag) for tag in set(_LIABILITIES.values())) + bs.net_income
    )
    if balance["AMG00440"] != balance["AMG00760"]:
        missing.append("balance_reconciliation")
    if details.opening_balances is None:
        missing.append("opening_balances")
    else:
        opening_assets = 0
        opening_liabilities = 0
        for name, amount in details.opening_balances.items():
            if type(amount) is not int:
                raise ValueError("Los saldos iniciales deben ser enteros.")
            if name in _ASSETS and name != "事業主貸":
                tag = f"AMG{int(_ASSETS[name][3:]) - 200:05d}"
                opening_assets += amount
            elif name in _LIABILITIES and name != "事業主借":
                end_tag = _LIABILITIES[name]
                tag = "AMG00600" if name == "元入金" else f"AMG{int(end_tag[3:]) - 130:05d}"
                opening_liabilities += amount
            else:
                raise ValueError("Saldo inicial sin clasificación fiscal: " + name)
            balance[tag] = _amount(balance, tag) + amount
        balance["AMG00230"] = opening_assets
        balance["AMG00610"] = opening_liabilities
        if opening_assets != opening_liabilities:
            raise ValueError("Los saldos iniciales no están balanceados.")
    emit_fields(page4, "KOA210-4", balance)


def build_xtx_document(
    draft: FilingDraftResult,
    identity: XtxIdentity,
    *,
    created_on: date,
    details: XtxDetails | None = None,
) -> XtxBuild:
    """Genera el XML completo conocido y enumera cada bloque pendiente."""
    from app.domain.tax.deductions import furusato_deduction
    from app.services.forms.etax_export import _build_body
    from app.services.forms.tax_office import resolve_tax_office
    from app.services.tax_rules import load_tax_rules

    if identity.name != draft.taxpayer_name:
        raise ValueError("La identidad no coincide con el contribuyente del borrador.")
    profile = draft.taxpayer_profile
    if profile is None or identity.address != profile.address:
        raise ValueError("La dirección no coincide con el perfil del borrador.")
    details = details or XtxDetails()
    missing: list[str] = ["official_import_acceptance"]
    if draft.tax.final_amount < 0:
        missing.append("refund_account")
    if draft.income_statement.net_income < 0:
        missing.append("business_loss_schedule")
    if any(line.account_name == "仕入" and line.amount for line in draft.income_statement.expenses):
        missing.append("inventory_schedule")
    expected_office = resolve_tax_office(profile.filing_office_key).etax_code
    if expected_office is None:
        missing.append("tax_office_assignment")
    elif identity.office_code != expected_office:
        raise ValueError("La oficina e-Tax no coincide con el perfil fiscal.")
    root, page = build_experimental_envelope(
        identity,
        created_by=identity.name,
        created_on=created_on,
        year=draft.year,
        name_kana=profile.name_kana,
        postal_code=profile.postal_code,
        occupation=profile.occupation,
    )
    form = root.find(f".//{{{SHOTOKU}}}KOA020")
    contents = root.find(f".//{{{SHOTOKU}}}CONTENTS")
    assert form is not None and contents is not None
    header: dict[str, int | str | ET.Element] = {
        "ABA00010": _reference("ABA00010", "NENBUN"),
        "ABA00020": _reference("ABA00020", "SHINKOKU_KBN"),
        "ABA00030": _reference("ABA00030", "ZEIMUSHO"),
        "ABA00090": _reference("ABA00090", "NOZEISHA_ADR"),
        "ABA00140": _reference("ABA00140", "NOZEISHA_NM"),
    }
    for tag, target, present in (
        ("ABA00080", "NOZEISHA_ZIP", profile.postal_code),
        ("ABA00130", "NOZEISHA_NM_KN", profile.name_kana),
        ("ABA00160", "SHOKUGYO", profile.occupation),
    ):
        if present:
            header[tag] = _reference(tag, target)
    if identity.my_number:
        header["ABA00125"] = _reference("ABA00125", "NOZEISHA_BANGO")
    else:
        missing.append("taxpayer_my_number")
    if identity.birth_date:
        header["ABA00200"] = _reference("ABA00200", "BIRTHDAY")
    else:
        missing.append("taxpayer_birth_date")
    for name, value in (
        ("name_kana", profile.name_kana),
        ("postal_code", profile.postal_code),
        ("occupation", profile.occupation),
    ):
        if not value:
            missing.append("taxpayer_" + name)
    if draft.filing_type != "shiroiro":
        header["ABA00240"] = _value("ABA00240", "kubun_CD", "1")
    temporary = ET.Element("temporary")
    _build_body(temporary, draft)
    body = temporary.find("ABB00000")
    assert body is not None
    values = {el.tag: int(el.text or "0") for el in body}
    # Subtotal oficial (13)-(25): excluye gastos médicos y donaciones (27)/(29).
    values["ABB00555"] = (
        draft.tax.total_income_deductions
        - draft.tax.deduction_breakdown.medical
        - draft.tax.deduction_breakdown.furusato
    )
    values["ABB00670"] = draft.tax.income_tax_after_credits
    if draft.tax.tax_credits:
        # El total agregado no identifica por sí solo un crédito de vivienda.
        values.pop("ABB00650", None)
    emit_fields(page, "KOA020-1", {**header, **values})
    _page2(form, details, missing)
    if sum(p.withholding for p in details.payers) != draft.tax.withholding_tax:
        missing.append("payer_withholding_reconciliation")
    for kind, expected in (("jigyo", draft.sales_revenue), ("kyuyo", draft.salary_revenue)):
        if sum(p.gross for p in details.payers if p.kind == kind) != expected:
            missing.append("payer_gross_reconciliation:" + kind)
    if any(str(item.kind) not in {"jigyo", "kyuyo"} for item in draft.tax.income_breakdown):
        missing.append("unsupported_income")
    db = draft.tax.deduction_breakdown
    for category, expected in (("social", db.social_insurance), ("ideco", db.ideco)):
        if sum(p.paid for p in details.premiums if p.category == category) != expected:
            missing.append("premium_reconciliation:" + category)
    if len(details.premiums) > 6:
        raise ValueError("El formulario admite como máximo seis tipos de seguros por página.")
    if details.premiums:
        page2 = form.find(f"{{{SHOTOKU}}}KOA020-2")
        assert page2 is not None
        group = ET.SubElement(page2, f"{{{SHOTOKU}}}ABH00000")
        premiums = ET.SubElement(group, f"{{{SHOTOKU}}}ABH00110")
        for premium in details.premiums:
            if (
                not premium.label.strip()
                or not 0 <= premium.outside_year_end_adjustment <= premium.paid
            ):
                raise ValueError("El detalle de primas es incompatible.")
            row = ET.SubElement(premiums, f"{{{SHOTOKU}}}ABH00120")
            for tag, value in (
                ("ABH00130", premium.label),
                ("ABH00140", str(premium.paid)),
                ("ABH00580", str(premium.outside_year_end_adjustment)),
            ):
                ET.SubElement(row, f"{{{SHOTOKU}}}{tag}").text = value
    insurance_values: dict[str, int | str | ET.Element] = {}
    for payment in details.insurance:
        for tag, amount in zip(
            INSURANCE_TAGS[payment.category],
            (payment.paid, payment.outside_year_end_adjustment), strict=True,
        ):
            insurance_values[tag] = _amount(insurance_values, tag) + amount
    life, earthquake = insurance_deductions(details.insurance)
    for category, actual, expected in (
        ("life_insurance", life, db.life_insurance),
        ("earthquake_insurance", earthquake, db.earthquake_insurance),
    ):
        if actual != expected:
            missing.append("insurance_reconciliation:" + category)
    categories = {r.category for r in details.insurance if r.paid}
    if {"earthquake", "old_damage"}.issubset(categories) and not details.separate_damage_contracts:
        missing.append("damage_contract_election")
    if insurance_values:
        page2 = form.find(f"{{{SHOTOKU}}}KOA020-2")
        assert page2 is not None
        # emit_fields conserva el orden oficial; fusionar el grupo evita duplicar ABH00000.
        temporary_page = ET.Element("temporary")
        emit_fields(temporary_page, "KOA020-2", insurance_values)
        source = temporary_page.find(f"{{{SHOTOKU}}}ABH00000")
        assert source is not None
        destination = page2.find(f"{{{SHOTOKU}}}ABH00000")
        if destination is None:
            page2.append(source)
        else:
            destination.extend(source)
    donated = sum(row.paid for row in details.donations)
    computed_donation = furusato_deduction(
        donated, draft.tax.total_income, load_tax_rules(draft.year)
    )
    if computed_donation != db.furusato:
        missing.append("donation_reconciliation")
    for index, donation in enumerate(details.donations):
        if not donation.name.strip() or not donation.location.strip() or donation.paid <= 0:
            raise ValueError("El comprobante de donación requiere nombre, dirección e importe.")
        # Un destinatario por página: no truncar nombres ni omitir ayuntamientos.
        donation_page = ET.SubElement(form, f"{{{SHOTOKU}}}KOA020-2")
        donation_values: dict[str, int | str | ET.Element] = {
            "ABC00010": _reference("ABC00010", "NENBUN"),
            "ABC00015": _reference("ABC00015", "SHINKOKU_KBN"),
            "ABC00040": _reference("ABC00040", "NOZEISHA_ADR"),
            "ABC00070": _reference("ABC00070", "NOZEISHA_NM"),
            "ABH00280": donation.location, "ABH00290": donation.name,
            "ABH00300": donation.paid,
        }
        if index == 0:
            # NTA 1155: también es obligatorio en la sección de 住民税.
            donation_values["ABI00240"] = donated
        emit_fields(donation_page, "KOA020-2", donation_values)
    for name in (
        "medical",
        "dependents",
        "spouse",
        "other",
    ):
        if getattr(db, name):
            missing.append("deduction_schedule:" + name)
    if draft.tax.tax_credits:
        missing.append("tax_credit_allocation")
    _annex(contents, draft, details, created_on, missing)
    # El RDF referencia cada formulario efectivamente incluido.
    seq = root.find(f".//{{{SHOTOKU}}}FORM_SEC/{{{RDF}}}Seq")
    assert seq is not None
    for extra in contents:
        if extra.tag == f"{{{SHOTOKU}}}KOA210":
            li = ET.SubElement(seq, f"{{{RDF}}}li")
            ET.SubElement(li, f"{{{RDF}}}Description", {"about": "#KOA210-1"})
    ET.indent(root, space="  ")
    payload = b'<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n' + ET.tostring(
        root, encoding="utf-8"
    )
    tags = tuple(
        sorted(
            {
                e.tag.split("}")[-1]
                for e in root.iter()
                if e.tag.split("}")[-1].startswith(
                    ("ABA", "ABB", "ABC", "ABD", "ABH", "ABI", "AMF", "AMG")
                )
            }
        )
    )
    return XtxBuild(payload, tuple(sorted(set(missing))), tags)
