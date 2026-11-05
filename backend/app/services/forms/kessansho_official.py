"""Estampado sobre el 青色申告決算書（一般用）oficial — 令和7 (FA3001).

Pone los números del `FilingDraftResult` sobre el 様式 oficial del NTA
(``templates/r07_kessansho.pdf``), página rotada `/Rotate 90`. Coordenadas en el
espacio VISUAL (lo que se ve), calibradas leyendo la grilla del 様式.

Páginas del 様式: p0 = 損益計算書 (P1), p3 = 貸借対照表 (P4). El overlay emite sólo
esas dos (omite las copias 控用 p4-7 y las P2/P3 de cálculos auxiliares).
"""

from __future__ import annotations

from typing import Literal

from app.models.enums import FilingType
from app.services.forms.drafting import FilingDraftResult
from app.services.forms.overlay import Field, render_overlay

_TEMPLATE = "r07_kessansho.pdf"
_PAGE_PL = 0   # 損益計算書 (P1)
_PAGE_BS = 3   # 貸借対照表 (P4)

AmountBlock = Literal["b1", "b2", "b3"]

# Centros reales de las 8 casillas naranjas de 金額 en el 損益計算書 (página 1).
# La primera casilla es más ancha y hay separadores de miles; no son equidistantes.
_PL_CELL_CENTERS: dict[AmountBlock, tuple[float, ...]] = {
    "b1": (189.0, 209.5, 225.0, 237.5, 251.5, 265.5, 279.5, 293.5),
    "b2": (426.5, 447.0, 462.5, 475.0, 489.0, 503.0, 517.0, 531.0),
    "b3": (664.0, 684.5, 700.0, 712.5, 726.5, 740.5, 754.5, 768.5),
}

_PL_DIGIT_SIZE = 11.8
_PL_DIGIT_Y_OFFSET = 3.2
_BS_AMOUNT_SIZE = 9.8
_BS_AMOUNT_Y_OFFSET = 3.2

# 経費 (勘定科目 → casilla del 損益計算書 oficial). El motor contable emite estos
# nombres; el resto cae a 雑費 ㉛.
_EXPENSE_BOX: dict[str, str] = {
    "租税公課": "8", "荷造運賃": "9", "水道光熱費": "10", "旅費交通費": "11",
    "通信費": "12", "広告宣伝費": "13", "接待交際費": "14", "損害保険料": "15",
    "修繕費": "16", "消耗品費": "17", "減価償却費": "18", "福利厚生費": "19",
    "給料賃金": "20", "外注工賃": "21", "利子割引料": "22", "地代家賃": "23",
    "貸倒金": "24", "雑費": "31",
}

# casilla → (bloque, y_baseline_visual). y = centro de fila + ~3 (baseline).
_BOX_POS: dict[str, tuple[AmountBlock, float]] = {
    # Bloque 1 — 売上原価
    "1": ("b1", 243),    # ① 売上(収入)金額
    "7": ("b1", 365),    # ⑦ 差引金額 (①−⑥)
    # Bloque 1 — 経費 ⑧〜⑯
    "8": ("b1", 393), "9": ("b1", 408), "10": ("b1", 424), "11": ("b1", 440),
    "12": ("b1", 455), "13": ("b1", 471), "14": ("b1", 487), "15": ("b1", 502),
    "16": ("b1", 518),
    # Bloque 2 — 経費 ⑰〜㉛ + 計㉜ + 差引㉝
    "17": ("b2", 236), "18": ("b2", 253), "19": ("b2", 270), "20": ("b2", 288),
    "21": ("b2", 305), "22": ("b2", 322), "23": ("b2", 340), "24": ("b2", 357),
    "31": ("b2", 478), "32": ("b2", 495), "33": ("b2", 518),
    # Bloque 3 — 所得
    "43": ("b3", 390),  # ㊸ 青色申告特別控除前の所得金額
    "44": ("b3", 410),  # ㊹ 青色申告特別控除額
    "45": ("b3", 440),  # ㊺ 所得金額
}


def _num(amount: int | None) -> str:
    """Formatea yenes con separadores; vacío si 0/None."""
    return "" if not amount else f"{amount}"


def _f(box: str, amount: int | None) -> list[Field]:
    """Dígitos de un monto en la casilla `box`, centrados en las cajas oficiales."""
    pos = _BOX_POS.get(box)
    if pos is None or not amount:
        return []
    block, y = pos
    centers = _PL_CELL_CENTERS[block]
    digits = _num(abs(amount))
    if len(digits) > len(centers):
        digits = digits[-len(centers):]
    start = len(centers) - len(digits)
    return [
        Field(ch, centers[start + i], y + _PL_DIGIT_Y_OFFSET, align="c", size=_PL_DIGIT_SIZE)
        for i, ch in enumerate(digits)
    ]


def _expense_box(account_name: str) -> str:
    """Casilla del 経費 por nombre de cuenta (default 雑費 ㉛)."""
    for key, box in _EXPENSE_BOX.items():
        if key in account_name:
            return box
    return "31"


def build_pl_fields(draft: FilingDraftResult) -> list[Field]:
    """Construye los `Field` del 損益計算書 (P1)."""
    pl = draft.income_statement
    fields: list[Field] = _profile_fields(draft)

    # ① 売上(収入)金額 y ⑦ 差引金額 (sin 売上原価 → ⑦ = ①).
    revenue = pl.total_revenue
    for box, amount in (("1", revenue), ("7", revenue)):
        fields.extend(_f(box, amount))

    # 経費 por 科目 (acumula los que caen a la misma casilla, p. ej. 雑費).
    by_box: dict[str, int] = {}
    for line in pl.expenses:
        by_box[_expense_box(line.account_name)] = (
            by_box.get(_expense_box(line.account_name), 0) + line.amount
        )
    for box, amount in by_box.items():
        fields.extend(_f(box, amount))

    # ㉜ 経費計 · ㉝ 差引金額 (⑦−㉜) · 所得.
    for box, amount in (
        ("32", pl.total_expense),
        ("33", pl.net_income),
        ("43", pl.net_income),               # ㊸ 青色前の所得金額
        ("44", draft.aoiro_deduction),       # ㊹ 青色申告特別控除額
        ("45", draft.business_income),       # ㊺ 所得金額
    ):
        fields.extend(_f(box, amount))
    return fields


# --- P4 貸借対照表 (columna 期末 12/31) ----------------------------------------
# Bordes derechos de la columna 期末 de cada lado (espacio visual).
_X_BS_ASSET = 306.0   # 資産の部 — 期末
_X_BS_LIAB = 463.0    # 負債・資本の部 — 期末

# 勘定科目 (substring) → (x_right, y_baseline) en el 期末. Sólo filas frecuentes;
# las que el motor no emite quedan en blanco.
_BS_ASSET_POS: dict[str, tuple[float, float]] = {
    "現金": (_X_BS_ASSET, 118), "当座預金": (_X_BS_ASSET, 135),
    "定期預金": (_X_BS_ASSET, 152), "その他の預金": (_X_BS_ASSET, 170),
    "受取手形": (_X_BS_ASSET, 190), "売掛金": (_X_BS_ASSET, 207),
    "有価証券": (_X_BS_ASSET, 225), "棚卸資産": (_X_BS_ASSET, 243),
    "前払金": (_X_BS_ASSET, 260), "貸付金": (_X_BS_ASSET, 278),
    "建物": (_X_BS_ASSET, 296), "工具器具備品": (_X_BS_ASSET, 348),
    "事業主貸": (_X_BS_ASSET, 518),
}
_BS_LIAB_POS: dict[str, tuple[float, float]] = {
    "支払手形": (_X_BS_LIAB, 118), "買掛金": (_X_BS_LIAB, 135),
    "借入金": (_X_BS_LIAB, 152), "未払金": (_X_BS_LIAB, 170),
    "前受金": (_X_BS_LIAB, 190), "預り金": (_X_BS_LIAB, 207),
    "事業主借": (_X_BS_LIAB, 483), "元入金": (_X_BS_LIAB, 503),
}
# 資産合計 / 負債資本合計 (fila 合計) y 青色前所得.
_BS_ASSET_TOTAL = (_X_BS_ASSET, 535)
_BS_LIAB_AOIRO_PRE = (_X_BS_LIAB, 520)   # 青色申告特別控除前の所得金額
_BS_LIAB_TOTAL = (_X_BS_LIAB, 535)


def _bs_pos(name: str, table: dict[str, tuple[float, float]]) -> tuple[float, float] | None:
    """Resuelve la posición de una cuenta del BS por substring del nombre."""
    for key, pos in table.items():
        if key in name:
            return pos
    return None


def build_bs_fields(draft: FilingDraftResult) -> list[Field]:
    """Construye los `Field` del 貸借対照表 (P4), columna 期末 (12/31)."""
    bs = draft.balance_sheet
    fields: list[Field] = []

    def put(pos: tuple[float, float] | None, amount: int) -> None:
        if pos and amount:
            fields.append(
                Field(
                    _num(abs(amount)),
                    pos[0],
                    pos[1] + _BS_AMOUNT_Y_OFFSET,
                    align="r",
                    size=_BS_AMOUNT_SIZE,
                )
            )

    for line in bs.assets:
        put(_bs_pos(line.account_name, _BS_ASSET_POS), line.amount)
    for line in bs.liabilities:
        put(_bs_pos(line.account_name, _BS_LIAB_POS), line.amount)
    # El 事業主貸/借 puede venir en `equity` según el motor; ubicarlos en su lado.
    for line in bs.equity:
        if "事業主貸" in line.account_name:
            put(_BS_ASSET_POS.get("事業主貸"), line.amount)
        elif "事業主借" in line.account_name:
            put(_BS_LIAB_POS.get("事業主借"), line.amount)
        elif "元入金" in line.account_name:
            put(_BS_LIAB_POS.get("元入金"), line.amount)

    # 青色申告特別控除前の所得金額 (期末) y totales de cuadre.
    put(_BS_LIAB_AOIRO_PRE, bs.net_income)
    put(_BS_ASSET_TOTAL, bs.total_assets)
    put(_BS_LIAB_TOTAL, bs.total_liabilities + bs.total_equity + bs.net_income)
    return fields


def _profile_fields(draft: FilingDraftResult) -> list[Field]:
    """Campos de encabezado comunes del 青色申告決算書."""
    prof = draft.taxpayer_profile
    if prof is None:
        return []
    fields: list[Field] = []
    if prof.address:
        fields.append(Field(_clip(prof.address, 22), 330, 91, align="l", size=8.2))
    if prof.name_kana:
        fields.append(Field(_clip(prof.name_kana, 14), 552, 85, align="c", size=6.5))
    fields.append(Field(_clip(prof.name, 10), 552, 102, align="c", size=9.2))
    if prof.occupation:
        fields.append(Field(_business_label(prof.occupation), 330, 146, align="l", size=6.6))
    return fields


def _business_label(text: str) -> str:
    """Ajusta 業種名 a la celda corta, sin invadir 屋号."""
    base = text
    for marker in ("（", "("):
        base = base.split(marker, 1)[0]
    return _clip(base.strip() or text, 9)


def _clip(text: str, limit: int) -> str:
    """Recorta texto de encabezado para no pisar las cajas oficiales."""
    return text if len(text) <= limit else text[:limit]


def render_kessansho_official(draft: FilingDraftResult) -> bytes:
    """Genera las cuatro páginas oficiales; P2 y P3 requieren revisión manual.

    Args:
        draft: Resultado del ensamblado del 確定申告.

    Returns:
        Bytes del PDF oficial, con valores en P1 y P4; P2 y P3 quedan vacías.
    """
    page_fields = {
        _PAGE_PL: build_pl_fields(draft),
        _PAGE_BS: build_bs_fields(draft),
    }
    return render_overlay(_TEMPLATE, page_fields, keep_pages=[0, 1, 2, 3])


_ = FilingType
