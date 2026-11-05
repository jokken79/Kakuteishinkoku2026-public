"""Constantes del esquema oficial e-Tax 令和7 (様式 KOA020, VR 23.0).

Fuente de verdad: ``etax_schema_r7.json`` (research 10 — "Esquema extraído del
CAB" del NTA). Este módulo expone los **tags ABA/ABB confirmados** del 申告書
第一表 como constantes con nombre legible, para que ``build_xtx`` mapee cada
valor del ``FilingDraftResult`` a su tag oficial SIN hardcodear ~50 strings
sueltos a lo largo del generador.

Estas constantes identifican las casillas monetarias existentes. Las rutas,
los tipos, las etiquetas y el orden oficiales se conservan en
``xtx_fields_r7.json``; ``xtx_document`` realiza el ensamblado. La validación
XSD no sustituye la verificación fiscal ni la prueba de importación.
"""

from __future__ import annotations

from typing import Final

# --- Sobre / 様式 ----------------------------------------------------------
ROOT_DATA: Final = "DATA"
FORM_ROOT: Final = "KOA020"  # 様式ID 申告書 第一表・第二表.
FORM_VERSION: Final = "23.0"  # VR.
FORM_PAGE1: Final = "KOA020-1"  # 申告書第一表 (sub-página).
HEADER_GROUP: Final = "ABA00000"  # 申告書見出し部 (cabecera).
BODY_GROUP: Final = "ABB00000"  # 申告内容第一表 (cuerpo).

# --- 年分 / era (ABA00010 = 元号区分 5=令和 + 年 2 dígitos) -----------------
ERA_KUBUN_REIWA: Final = "5"  # 令和.
# 申告の種類 (ABA00020): 1=確定 / 2=修正 / 3=準確定 / 4=準確定修正.
SHINKOKU_KAKUTEI: Final = "1"
# 青色区分 (ABA00240): 1=該当 (青色申告者) / 2=非該当.
AOIRO_GAITOU: Final = "1"

# --- Cabecera (ABA*) — header_fields del JSON ------------------------------
TAG_NENBUN: Final = "ABA00010"  # 年分 (元号区分 + 年).
TAG_SHINKOKU_SHURUI: Final = "ABA00020"  # 申告の種類.
TAG_ZEIMUSHO: Final = "ABA00030"  # 税務署名.
TAG_YUBIN: Final = "ABA00080"  # 郵便番号.
TAG_JUSHO_UE: Final = "ABA00090"  # 住所 (上段).
TAG_JUSHO_SHITA: Final = "ABA00095"  # 住所 (下段).
TAG_MYNUMBER: Final = "ABA00125"  # 個人番号 (マイナンバー) — opcional.
TAG_FURIGANA: Final = "ABA00130"  # フリガナ.
TAG_SHIMEI: Final = "ABA00140"  # 氏名.
TAG_SHOKUGYO: Final = "ABA00160"  # 職業.
TAG_AOIRO_KUBUN: Final = "ABA00240"  # 青色区分.

# --- 収入金額等 (ABB*) -----------------------------------------------------
TAG_REVENUE_JIGYO: Final = "ABB00030"  # 事業：営業等 (収入金額) ㋐.
TAG_REVENUE_KYUYO: Final = "ABB00080"  # 給与 (収入金額) ㋕.

# --- 所得金額等 (ABB*) -----------------------------------------------------
TAG_INCOME_JIGYO: Final = "ABB00300"  # 事業：営業等 (所得) ①.
TAG_INCOME_KYUYO: Final = "ABB00370"  # 給与 (所得) ⑥.
TAG_INCOME_TOTAL: Final = "ABB00410"  # 合計 (所得金額) ⑫.

# --- 所得控除 (ABB*) -------------------------------------------------------
TAG_DED_SHAKAI: Final = "ABB00450"  # 社会保険料控除 ⑬.
TAG_DED_IDECO: Final = "ABB00460"  # 小規模企業共済等掛金控除 ⑭.
TAG_DED_LIFE: Final = "ABB00470"  # 生命保険料控除 ⑮.
TAG_DED_EARTHQUAKE: Final = "ABB00480"  # 地震保険料控除 ⑯.
TAG_DED_FURUSATO: Final = "ABB00490"  # 寄附金控除 ㉘.
TAG_DED_STUDENT_DISABILITY: Final = "ABB00510"  # 勤労学生・障害者控除.
TAG_DED_MEDICAL: Final = "ABB00440"  # 医療費控除 ㉗.
TAG_DED_SPOUSE: Final = "ABB00520"  # 配偶者(特別)控除 (控除額) ㉑㉒.
TAG_DED_DEPENDENTS: Final = "ABB00540"  # 扶養控除 ㉓.
TAG_DED_KISO: Final = "ABB00550"  # 基礎控除 ㉔.
TAG_DED_TOTAL: Final = "ABB00560"  # 所得控除 合計 ㉚.

# --- 税額計算 (ABB*) -------------------------------------------------------
TAG_TAXABLE_INCOME: Final = "ABB00580"  # 課税される所得金額 ㉛ (千円未満切捨て).
TAG_TAX_BASE: Final = "ABB00590"  # 上の㉛に対する税額 ㉜.
TAG_HOUSING_LOAN: Final = "ABB00650"  # 住宅借入金等特別控除 ㊱ (百円未満切捨て).
TAG_TAX_AFTER_CREDITS: Final = "ABB01010"  # 再差引所得税額 (基準所得税額) ㊹.
TAG_RECONSTRUCTION: Final = "ABB01020"  # 復興特別所得税額 ㊺.
TAG_TAX_TOTAL: Final = "ABB01030"  # 所得税及び復興特別所得税の額 ㊻.
TAG_WITHHOLDING: Final = "ABB00710"  # 源泉徴収税額 ㊽.
TAG_NOZEI_GAKU: Final = "ABB00720"  # 申告納税額 ㊿ (百円未満切捨て; <0 = 還付).
TAG_PREPAYMENT: Final = "ABB00730"  # 予定納税額 51.
TAG_PAYMENT: Final = "ABB00750"  # 第3期分の納付税額 52.
TAG_REFUND: Final = "ABB00760"  # 第3期分：還付される税金.
TAG_AOIRO_DEDUCTION: Final = "ABB00800"  # 青色申告特別控除額 (59).
