"""Enumeraciones del dominio fiscal.

Todos los enums se almacenan por su `value` (string corto en ingles/romaji)
para que la BD sea legible y estable entre dialectos. Los comentarios indican
el termino japones de negocio correspondiente.
"""

from __future__ import annotations

import enum


class FilingType(enum.StrEnum):
    """Modalidad de declaracion (申告区分)."""

    AOIRO_65 = "aoiro_65"  # 青色申告 65万控除 (複式簿記 + e-Tax)
    AOIRO_55 = "aoiro_55"  # 青色申告 55万控除 (複式簿記 + papel)
    AOIRO_10 = "aoiro_10"  # 青色申告 10万控除 (簡易簿記)
    SHIROIRO = "shiroiro"  # 白色申告


class ConsumptionMethod(enum.StrEnum):
    """Metodo de calculo del 消費税."""

    HONSOKU = "honsoku"  # 本則課税
    KANI = "kani"  # 簡易課税
    TOKUREI_2WARI = "tokurei_2wari"  # 2割特例


class AccountCategory(enum.StrEnum):
    """Categoria contable del 勘定科目."""

    ASSET = "asset"  # 資産
    LIABILITY = "liability"  # 負債
    EQUITY = "equity"  # 資本
    REVENUE = "revenue"  # 収益
    EXPENSE = "expense"  # 費用


class FiscalYearStatus(enum.StrEnum):
    """Estado del 年度."""

    OPEN = "open"
    CLOSED = "closed"
    FILED = "filed"


class TransactionSource(enum.StrEnum):
    """Origen del 取引."""

    OCR = "ocr"
    CSV = "csv"
    MANUAL = "manual"
    BANK = "bank"


class TransactionStatus(enum.StrEnum):
    """Estado de revision del 取引."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class JournalSide(enum.StrEnum):
    """Lado del asiento contable."""

    DEBIT = "debit"  # 借方
    CREDIT = "credit"  # 貸方


class DeductionType(enum.StrEnum):
    """Tipo de 所得控除 (deduccion)."""

    KISO = "kiso"  # 基礎控除
    SHAKAI_HOKEN = "shakai_hoken"  # 社会保険料控除
    IRYOHI = "iryohi"  # 医療費控除
    SEIMEI_HOKEN = "seimei_hoken"  # 生命保険料控除
    JISHIN_HOKEN = "jishin_hoken"  # 地震保険料控除
    FURUSATO = "furusato"  # ふるさと納税 (寄附金控除)
    IDECO = "ideco"  # iDeCo (小規模企業共済等掛金控除)
    FUYO = "fuyo"  # 扶養控除
    HAIGUSHA = "haigusha"  # 配偶者控除
    # 税額控除 (NO es 所得控除): se resta del impuesto, no de la base imponible.
    # Se persiste como `Deduction` por homogeneidad de almacenamiento, pero el
    # draft lo lee como `tax_credit`, no como 所得控除 (ver drafting.py).
    HOUSING_LOAN = "housing_loan"  # 住宅借入金等特別控除 (住宅ローン控除)
    DISABILITY_SELF = "disability_self"  # 本人の一般障害者控除
    OTHER = "other"


class HouseholdCategory(enum.StrEnum):
    """費目 — categoría de un gasto del 家計簿 (libro de gastos personales).

    NO es fiscal: el 家計簿 trackea gastos PERSONALES que NO entran a la
    declaración. Categorías "ざっくり" estándar de un 家計簿 doméstico, no
    relacionadas con los 勘定科目 contables del negocio.
    """

    SHOKUHI = "shokuhi"  # 食費
    NICHIYOHIN = "nichiyohin"  # 日用品
    JUKYOHI = "jukyohi"  # 住居費
    SUIDOKONETSU = "suidokonetsu"  # 水道光熱費
    KOTSUHI = "kotsuhi"  # 交通費
    TSUSHINHI = "tsushinhi"  # 通信費
    KOSAIHI = "kosaihi"  # 交際費
    GORAKUHI = "gorakuhi"  # 娯楽費
    IRYOHI = "iryohi"  # 医療費
    IFUKU = "ifuku"  # 衣服
    KYOIKU = "kyoiku"  # 教育
    SONOTA = "sonota"  # その他


class IncomeType(enum.StrEnum):
    """Tipo de 所得 (uno de los 10 tipos)."""

    KYUYO = "kyuyo"  # 給与所得
    JIGYO = "jigyo"  # 事業所得
    ZATSU = "zatsu"  # 雑所得
    FUDOSAN = "fudosan"  # 不動産所得
    HAITO = "haito"  # 配当所得
    RISHI = "rishi"  # 利子所得
    JOTO = "joto"  # 譲渡所得
    ICHIJI = "ichiji"  # 一時所得
    TAISHOKU = "taishoku"  # 退職所得
    SANRIN = "sanrin"  # 山林所得


class DepreciationMethod(enum.StrEnum):
    """Metodo de 減価償却."""

    TEIGAKU = "teigaku"  # 定額法
    TEIRITSU = "teiritsu"  # 定率法


class FilingDraftStatus(enum.StrEnum):
    """Estado del 申告書ドラフト."""

    DRAFT = "draft"
    READY = "ready"
    FILED = "filed"


class SalesDocumentType(enum.StrEnum):
    """Tipo de documento comercial emitido (売上書類)."""

    ESTIMATE = "estimate"  # 見積書
    DELIVERY_NOTE = "delivery_note"  # 納品書
    INVOICE = "invoice"  # 請求書 / 適格請求書
    RECEIPT = "receipt"  # 領収書
    PURCHASE_ORDER = "purchase_order"  # 発注書
    ORDER_ACKNOWLEDGEMENT = "order_acknowledgement"  # 発注請書
    CONSOLIDATED_INVOICE = "consolidated_invoice"  # 合算請求書
    CORRECTED_INVOICE = "corrected_invoice"  # 修正請求書


class SalesDocumentStatus(enum.StrEnum):
    """Ciclo de vida de un documento comercial."""

    DRAFT = "draft"  # 下書き
    ISSUED = "issued"  # 発行済み
    SENT = "sent"  # 送付済み
    AWAITING_PAYMENT = "awaiting_payment"  # 入金待ち
    PARTIALLY_PAID = "partially_paid"  # 一部入金
    PAID = "paid"  # 入金済み
    VOIDED = "voided"  # 取消


class SalesTaxCategory(enum.StrEnum):
    """Tratamiento fiscal de una linea comercial."""

    STANDARD_10 = "standard_10"  # 10%
    REDUCED_8 = "reduced_8"  # 軽減税率 8%
    EXEMPT = "exempt"  # 非課税
    OUT_OF_SCOPE = "out_of_scope"  # 対象外


class TaxRoundingMode(enum.StrEnum):
    """Metodo de redondeo del impuesto por tasa y documento."""

    FLOOR = "floor"  # 切り捨て
    ROUND = "round"  # 四捨五入
    CEIL = "ceil"  # 切り上げ


class SalesPriceMode(enum.StrEnum):
    """Interpretacion del precio ingresado en las lineas."""

    EXCLUSIVE = "exclusive"  # 税抜
    INCLUSIVE = "inclusive"  # 税込


class SalesPaymentMethod(enum.StrEnum):
    """Medio de cobro de una factura/recibo."""

    CASH = "cash"  # 現金
    BANK_TRANSFER = "bank_transfer"  # 銀行振込
    CARD = "card"  # カード
    OTHER = "other"  # その他
