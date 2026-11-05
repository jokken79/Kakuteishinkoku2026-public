"""Estampado de valores sobre el 確定申告書 第一表・第二表 oficial (令和7年分).

Mapea los números del `FilingDraftResult` a las coordenadas de cada casilla del
様式 oficial del NTA (``templates/r07_01.pdf``) y produce el PDF oficial real con
los datos del contribuyente, vía `overlay.render_overlay`.

Las coordenadas (sistema top-left, pt) se calibraron extrayendo con PyMuPDF la
posición de cada etiqueta/número de casilla del propio 様式 oficial — no son
estimaciones a ojo. Columnas de montos: izquierda (収入/所得/控除) alineada a la
derecha en X≈287; derecha (税金の計算) en X≈531.
"""

from __future__ import annotations

from app.models.enums import FilingType
from app.services.forms.drafting import FilingDraftResult
from app.services.forms.overlay import Field, render_overlay
from app.services.forms.tax_office import resolve_tax_office

# 様式 oficial: r07_01.pdf = pág0 第一表 · pág1 第二表 · pág2/3 控用 (copias).
_TEMPLATE = "r07_01.pdf"
_PAGE_DAI1 = 0
_PAGE_DAI2 = 1

# Bordes derechos de las columnas de montos (alineación derecha), calibrados
# contra la grilla real del 様式 (borde derecho de celdas de dígitos = 278.6 izq,
# 530.2 der; se deja ~1.5pt de margen interior).
_X_LEFT = 272.3   # Centro de la última casilla de importes izquierda.
_X_RIGHT = 523.9  # Centro de la última casilla de importes derecha.

# Las 人的控除 (寡婦/障害者/配偶者/扶養/特定親族/基礎) llevan los 4 ceros finales
# PRE-IMPRESOS en el 様式 (son múltiplos de 万). Sólo se estampan los dígitos de
# 万 (monto // 10.000), alineados a la derecha justo antes de esos ceros (x≈221).
_X_MAN = 216.4

# Tamaño de fuente de los montos.
_AMOUNT_SIZE = 12.8
_AMOUNT_TRACKING = 13.97


def _num(amount: int | None) -> str:
    """Formatea un entero de yenes para la casilla oficial (con separadores).

    El 様式 oficial no lleva el símbolo ¥; sólo el número. Los importes negativos
    (p. ej. 還付) se estampan en su casilla propia (53), por lo que aquí se usa el
    valor absoluto que corresponda a la casilla.

    Args:
        amount: Monto en yenes o ``None``.

    Returns:
        Cadena con separador de millares, o ``""`` si es ``None``/0.
    """
    if not amount:
        return ""
    return f"{amount}"


def _amount(x: float, y: float, amount: int | None) -> Field:
    """Atajo: `Field` de un monto alineado a la derecha (con separadores)."""
    return Field(_num(amount), x, y, align="r", size=_AMOUNT_SIZE, tracking=_AMOUNT_TRACKING)


def _amount_man(y: float, amount: int | None) -> Field:
    """`Field` de una 人的控除: sólo los dígitos de 万 (los 0000 ya van impresos).

    Args:
        y: Baseline (top-left) de la fila.
        amount: Monto en yenes (múltiplo de 10.000) o ``None``.

    Returns:
        `Field` con ``amount // 10000`` alineado a la derecha en `_X_MAN`.
    """
    text = "" if not amount else f"{amount // 10_000}"
    return Field(text, _X_MAN, y, align="r", size=_AMOUNT_SIZE, tracking=_AMOUNT_TRACKING)


def _amount_trunc(y: float, amount: int | None, unit: int, x_right: float) -> Field:
    """`Field` de una casilla con ceros finales PRE-IMPRESOS en el 様式.

    Algunas casillas llevan ya impresos los ceros del redondeo legal: ㉛ 課税
    される所得金額 (千円, ``000``) y 52 納める税金 (100円, ``00``). Sólo se estampan
    los dígitos por encima de esa unidad, alineados a la izquierda de los ceros.

    Args:
        y: Baseline (top-left) de la fila.
        amount: Monto en yenes o ``None``.
        unit: Unidad pre-impresa (1000 para 千円, 100 para 100円).
        x_right: Borde derecho de alineación (a la izquierda de los ceros).

    Returns:
        `Field` con ``amount // unit`` (con separadores) o vacío.
    """
    text = "" if not amount else f"{amount // unit}"
    return Field(text, x_right, y, align="r", size=_AMOUNT_SIZE, tracking=_AMOUNT_TRACKING)


def build_dai1_fields(draft: FilingDraftResult) -> list[Field]:
    """Construye los `Field` del 第一表 (収入・所得・控除・税額)."""
    tax = draft.tax
    db = tax.deduction_breakdown
    by_kind: dict[str, int] = {}
    for item in tax.income_breakdown:
        kind = str(item.kind)
        by_kind[kind] = by_kind.get(kind, 0) + item.amount
    kyuyo = by_kind.get("kyuyo", 0)

    fields: list[Field] = []

    # --- 収入金額等 (columna izquierda) ---
    fields.append(_amount(_X_LEFT, 161.9, draft.sales_revenue))   # ㋐ 営業等
    if draft.salary_revenue:
        fields.append(_amount(_X_LEFT, 227.9, draft.salary_revenue))  # 給与収入 bruto

    # --- 所得金額等 ---
    fields.append(_amount(_X_LEFT, 343.4, draft.business_income))  # ① 事業(営業等)
    if "fudosan" in by_kind:
        fields.append(_amount(_X_LEFT, 376.4, by_kind["fudosan"]))  # ③ 不動産
    if "haito" in by_kind:
        fields.append(_amount(_X_LEFT, 409.4, by_kind["haito"]))    # ⑤ 配当
    if kyuyo:
        fields.append(_amount(_X_LEFT, 425.9, kyuyo))               # ⑥ 給与
    if "zatsu" in by_kind:
        fields.append(_amount(_X_LEFT, 491.9, by_kind["zatsu"]))    # ⑩ 雑(合計)
    if "ichiji" in by_kind:
        fields.append(_amount(_X_LEFT, 508.4, by_kind["ichiji"]))   # ⑪ 総合譲渡・一時
    fields.append(_amount(_X_LEFT, 524.9, tax.total_income))        # ⑫ 合計

    # --- 所得から差し引かれる金額 (所得控除) ---
    # Montos reales (no múltiplos de 万): número completo a la derecha.
    fields.append(_amount(_X_LEFT, 541.4, db.social_insurance))     # ⑬ 社会保険料
    fields.append(_amount(_X_LEFT, 557.9, db.ideco))              # ⑭ 小規模企業共済等
    fields.append(_amount(_X_LEFT, 574.4, db.life_insurance))     # ⑮ 生命保険料
    fields.append(_amount(_X_LEFT, 590.9, db.earthquake_insurance))  # ⑯ 地震保険料
    # 人的控除 (0000 pre-impreso): sólo dígitos de 万.
    if db.ordinary_disability_self:
        # La columna ⑳ es 勤労学生・障害者; el resto de `other` no está clasificado.
        fields.append(_amount_man(623.9, 270_000))
    fields.append(_amount_man(640.4, db.spouse))                 # ㉑㉒ 配偶者(特別)
    fields.append(_amount_man(656.9, db.dependents))            # ㉓ 扶養
    # ㉔ 特定親族特別控除 (令和7新設) — aún no modelado (0).
    fields.append(_amount_man(689.9, db.kiso))                  # ㉕ 基礎控除
    subtotal = (
        db.social_insurance + db.ideco + db.life_insurance
        + db.earthquake_insurance + db.other + db.spouse
        + db.dependents + db.kiso
    )
    fields.append(_amount(_X_LEFT, 706.4, subtotal))           # ㉖ ⑬〜㉕の計
    fields.append(_amount(_X_LEFT, 739.4, db.medical))         # ㉘ 医療費
    fields.append(_amount(_X_LEFT, 755.8, db.furusato))       # ㉙ 寄附金
    fields.append(_amount(_X_LEFT, 772.3, tax.total_income_deductions))  # ㉚ 合計

    # --- 税金の計算 (columna derecha) ---
    # ㉛ 課税所得: 千円未満切り捨て → "000" pre-impreso; sólo dígitos de 千.
    fields.append(_amount_trunc(161.9, tax.taxable_income, 1000, 482.0))  # ㉛ 課税所得
    fields.append(_amount(_X_RIGHT, 178.4, tax.income_tax_base))       # ㉜ 税額
    fields.append(_amount(_X_RIGHT, 310.4, tax.income_tax_after_credits))  # ㊹ 基準所得税額
    fields.append(_amount(_X_RIGHT, 326.9, tax.reconstruction_tax))   # ㊺ 復興特別所得税
    fields.append(_amount(_X_RIGHT, 343.4, tax.total_tax))           # ㊻ 所得税及び復興税
    fields.append(_amount(_X_RIGHT, 376.4, tax.withholding_tax))   # ㊾ 源泉徴収税額
    declared_tax = tax.total_tax - tax.withholding_tax
    if declared_tax > 0:
        declared_tax = declared_tax // 100 * 100
    fields.append(_amount(_X_RIGHT, 392.9, declared_tax))  # ㊿ 申告納税額
    if tax.estimated_prepayment:
        fields.append(_amount(_X_RIGHT, 409.4, tax.estimated_prepayment))  # 51 予定納税
    if tax.final_amount < 0:
        # 53 還付される税金 (monto exacto; sin ceros pre-impresos).
        fields.append(_amount(_X_RIGHT, 442.4, abs(tax.final_amount)))
    else:
        # 52 納める税金: 100円未満切り捨て → "00" pre-impreso; sólo dígitos de 100.
        fields.append(_amount_trunc(425.9, tax.final_amount, 100, 496.0))
    if draft.aoiro_deduction:
        fields.append(_amount(_X_RIGHT, 541.4, draft.aoiro_deduction))  # 59 青色申告特別控除額

    # --- Encabezado (氏名 / 屋号 / 住所) ---
    prof = draft.taxpayer_profile
    name = prof.name if prof else draft.taxpayer_name
    office = resolve_tax_office(prof.filing_office_key if prof else None)
    # Encabezado: las casillas no son uniformes (〒 y 生年月日 tienen saltos por
    # guion/puntos), por eso se colocan carácter por carácter en el centro real.
    fields.append(Field(office.header_name, 76, 34, align="l", size=8.2))
    if prof and prof.postal_code:
        postal_digits = "".join(ch for ch in prof.postal_code if ch.isdigit())
        fields.extend(
            _cell_fields(
                postal_digits[:7],
                [87.6, 101.6, 115.6, 136.5, 150.5, 164.5, 178.4],
                59.7,
                size=12.0,
            )
        )
    if prof and prof.birth_date_label:
        birth_digits = _birth_digits(prof.birth_date_label)
        if birth_digits:
            fields.extend(
                _cell_fields(
                    birth_digits,
                    [419.1, 439.4, 453.4, 474.3, 488.3, 509.3, 523.2],
                    59.7,
                    size=12.0,
                )
            )
    if prof and prof.address:
        fields.append(Field(_clip(prof.address, 24), 70, 104, align="l", size=9.6))
    if prof and prof.name_kana:
        fields.extend(
            _cell_fields(
                _clip(prof.name_kana, 14),
                [
                    341.6, 355.6, 369.6, 383.5, 397.5, 411.5, 425.4,
                    439.4, 453.4, 467.4, 481.3, 495.3, 509.3, 523.2,
                ],
                77.9,
                size=8.8,
            )
        )
    if name:
        fields.append(Field(_clip(name, 12), 431.9, 103.2, align="c", size=11.5))  # 氏名
    if prof and prof.occupation:
        fields.append(Field(_clip(prof.occupation, 10), 328, 155, align="l", size=7.4))

    return fields


def build_dai2_fields(draft: FilingDraftResult) -> list[Field]:
    """Construye los `Field` del 第二表 (所得の内訳・源泉徴収税額).

    Estampa el 氏名 y la tabla 所得の内訳 (一行 de 事業 con 収入金額 + 源泉徴収税額) y
    el 源泉徴収税額の合計額. El desglose de 保険料 por póliza y el detalle de
    配偶者・扶養 requieren datos por ítem que el motor agrega; se dejan para una
    pasada con esos datos (el 第一表 ya lleva los importes de cada 控除).
    """
    tax = draft.tax
    prof = draft.taxpayer_profile
    name = prof.name if prof else draft.taxpayer_name
    fields: list[Field] = []
    if name:
        fields.append(Field(_clip(name, 12), 180, 118, align="c", size=12))   # 氏名

    # 所得の内訳: fila 事業（営業等）.
    sales = draft.sales_revenue
    withholding = tax.withholding_total
    if sales or withholding:
        fields.append(Field("事業", 48, 243, align="l", size=8.5))       # 所得の種類
        fields.append(Field("営業等", 80, 243, align="l", size=8))       # 種目
        if sales:
            fields.append(Field(f"{sales}", 236, 243, align="r", size=8.8))  # 収入金額
        if withholding:
            fields.append(Field(f"{withholding}", 285, 243, align="r", size=8.8))  # 源泉
        # 源泉徴収税額の合計額 (→ ㊾ del 第一表).
        if withholding:
            fields.append(Field(f"{withholding}", 285, 333, align="r", size=9.6))
    return fields


def render_shinkokusho_official(draft: FilingDraftResult) -> bytes:
    """Genera el 確定申告書 第一表・第二表 sobre el 様式 oficial (令和7).

    Args:
        draft: Resultado del ensamblado del 確定申告.

    Returns:
        Bytes del PDF oficial (págs 第一表 + 第二表) con los valores estampados.
    """
    page_fields = {
        _PAGE_DAI1: build_dai1_fields(draft),
        _PAGE_DAI2: build_dai2_fields(draft),
    }
    # Sólo 第一表 + 第二表 (págs 0 y 1); se omiten las copias 控用 (2 y 3).
    return render_overlay(_TEMPLATE, page_fields, keep_pages=[_PAGE_DAI1, _PAGE_DAI2])


# Nota: 'filing_type' se usará para variantes (白色 no lleva ㉕ 青色控除, etc.).
_ = FilingType


def _clip(text: str, limit: int) -> str:
    """Recorta texto de encabezado para evitar que invada casillas vecinas."""
    return text if len(text) <= limit else text[:limit]


def _cell_fields(text: str, centers: list[float], y: float, *, size: float) -> list[Field]:
    """Campos de un carácter por casilla para grillas no uniformes."""
    fields: list[Field] = []
    for ch, x in zip(text, centers, strict=False):
        if ch.isspace():
            continue
        fields.append(Field(ch, x, y, align="c", size=size))
    return fields


def _birth_digits(label: str) -> str:
    """Convierte '昭和54年6月12日' en los dígitos de casilla '3540612'."""
    era = "3" if label.startswith("昭和") else "4" if label.startswith("平成") else "5"
    nums: list[str] = []
    current = ""
    for ch in label:
        if ch.isdigit():
            current += ch
        elif current:
            nums.append(current)
            current = ""
    if current:
        nums.append(current)
    if len(nums) < 3:
        return ""
    year, month, day = nums[:3]
    return f"{era}{int(year):02d}{int(month):02d}{int(day):02d}"
