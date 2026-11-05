"""Estampado sobre el 収支内訳書（一般用）oficial — 令和7 (FA7050).

Documento del **白色申告** (sin 貸借対照表). Pone los números del
`FilingDraftResult` sobre el 様式 oficial del NTA (``templates/r07_05.pdf``),
página rotada `/Rotate 90`, vía `overlay.render_overlay`.

Layout de la tabla principal (mitad izquierda), dos sub-columnas espejadas:
    col1 = 科目 | 金額   (収入①〜④, 売上原価⑤〜⑨, 差引金額⑩, 経費 ⑪〜⑯ + イ/ロ)
    col2 = 金額 | 科目   (その他の経費, 雑費, 経費計⑱, 専従者控除前⑲, 所得金額㉑)

Coordenadas en espacio VISUAL (lo que se ve), calibradas sobre la grilla del 様式.
"""

from __future__ import annotations

from app.services.forms.drafting import FilingDraftResult
from app.services.forms.overlay import Field, render_overlay

_TEMPLATE = "r07_05.pdf"
_PAGE = 0  # 収支内訳書 P1.

# Bordes derechos de las dos columnas de 金額 (visual).
_X1 = 170.0  # col1 金額.
_X2 = 256.0  # col2 金額.
_SIZE = 10.5
_TRACKING = 7.6

# 経費 (勘定科目 substring → (x_right, y_baseline visual)). El motor emite estos
# nombres; el resto cae a 雑費.
_EXPENSE_POS: dict[str, tuple[float, float]] = {
    # col1: 経費 numerados ⑪〜⑯ + その他 イ/ロ/ハ (租税公課/荷造運賃/水道光熱費).
    "給料賃金": (_X1, 390), "外注工賃": (_X1, 407), "減価償却費": (_X1, 424),
    "貸倒金": (_X1, 442), "地代家賃": (_X1, 459), "利子割引料": (_X1, 476),
    "租税公課": (_X1, 493), "荷造運賃": (_X1, 510), "水道光熱費": (_X1, 527),
    # col2: その他の経費 preimpresos (ニ〜).
    "旅費交通費": (_X2, 220), "通信費": (_X2, 236), "広告宣伝費": (_X2, 253),
    "接待交際費": (_X2, 270), "損害保険料": (_X2, 288), "修繕費": (_X2, 305),
    "消耗品費": (_X2, 323), "福利厚生費": (_X2, 340),
}
_X2_ZATSU = (_X2, 451)        # 雑費.
_X2_KEIHI_TOTAL = (_X2, 481)  # ⑱ 経費計.
_X2_PRE_INCOME = (_X2, 498)   # ⑲ 専従者控除前の所得金額 (⑩−⑱).
_X2_INCOME = (_X2, 533)       # ㉑ 所得金額.


def _num(amount: int | None) -> str:
    return "" if not amount else f"{amount}"


def _expense_pos(name: str) -> tuple[float, float]:
    for key, pos in _EXPENSE_POS.items():
        if key in name:
            return pos
    return _X2_ZATSU


def build_shushi_fields(draft: FilingDraftResult) -> list[Field]:
    """Construye los `Field` del 収支内訳書 P1."""
    pl = draft.income_statement
    fields: list[Field] = []

    def put(pos: tuple[float, float], amount: int | None) -> None:
        if amount:
            fields.append(
                Field(_num(amount), pos[0], pos[1], align="r", size=_SIZE, tracking=_TRACKING)
            )

    revenue = pl.total_revenue
    put((_X1, 220), revenue)   # ① 売上(収入)金額
    put((_X1, 270), revenue)   # ④ 計 (sin 家事消費/雑収入)
    put((_X1, 372), revenue)   # ⑩ 差引金額 (sin 売上原価)

    # 経費 por 科目 (acumula los que comparten celda, p. ej. 雑費).
    by_pos: dict[tuple[float, float], int] = {}
    for line in pl.expenses:
        pos = _expense_pos(line.account_name)
        by_pos[pos] = by_pos.get(pos, 0) + line.amount
    for pos, amount in by_pos.items():
        put(pos, amount)

    put(_X2_KEIHI_TOTAL, pl.total_expense)   # ⑱ 経費計
    put(_X2_PRE_INCOME, pl.net_income)       # ⑲ 専従者控除前の所得金額
    put(_X2_INCOME, draft.business_income)   # ㉑ 所得金額
    return fields


def render_shushi_official(draft: FilingDraftResult) -> bytes:
    """Genera el 収支内訳書（一般用）con P2 sin completar (白色).

    Args:
        draft: Resultado del ensamblado del 確定申告.

    Returns:
        PDF oficial con valores en P1 y P2 para completar manualmente.
    """
    return render_overlay(_TEMPLATE, {_PAGE: build_shushi_fields(draft)}, keep_pages=[0, 1])
