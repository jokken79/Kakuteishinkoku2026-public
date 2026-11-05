/**
 * Catalogo del 控除ウィザード: las preguntas conversacionales, la ayuda
 * contextual (que documento hace falta) y el icono por tipo de 所得控除.
 *
 * El wizard es "質問に答えるだけ": cada paso hace UNA pregunta clara en japones,
 * pide el monto y explica el 控除証明書 necesario. UI en japones, codigo en ingles.
 */
import type { DeductionType } from "./api";
import type { IconName } from "../components/Icon";

/** Definicion de un paso del wizard (una categoria de 控除). */
export interface DeductionStep {
  /** Tipo de 控除 (clave estable). */
  readonly type: DeductionType;
  /** Etiqueta corta de la categoria (japones). */
  readonly label: string;
  /** Pregunta conversacional ("〜していますか？"). */
  readonly question: string;
  /** Ayuda contextual: que es y como se calcula. */
  readonly help: string;
  /** Documento necesario (控除証明書 etc.). */
  readonly document: string;
  /** Etiqueta del campo de monto (japones). */
  readonly amountLabel: string;
  /** Placeholder de ejemplo del monto. */
  readonly placeholder: string;
  /** Icono line-art representativo. */
  readonly icon: IconName;
  /** ``true`` si la categoria admite un campo de reembolso (医療費). */
  readonly hasReimbursement?: boolean;
}

/**
 * Pasos del wizard, en el orden conversacional recomendado: primero los que casi
 * todos tienen (社会保険・生命保険), luego los condicionales (iDeCo・ふるさと・医療費),
 * cerrando con familia (配偶者・扶養). El 基礎控除 NO esta: es automatico.
 */
export const DEDUCTION_STEPS: readonly DeductionStep[] = [
  {
    type: "shakai_hoken",
    label: "社会保険料控除",
    question: "国民健康保険や年金を支払いましたか？",
    help: "国民健康保険・国民年金・国民年金基金などの支払いは、全額が控除の対象です（上限なし）。ほとんどの方が対象になります。",
    document: "社会保険料（国民年金）控除証明書",
    amountLabel: "年間の支払額",
    placeholder: "例：300,000",
    icon: "shield",
  },
  {
    type: "seimei_hoken",
    label: "生命保険料控除",
    question: "生命保険に入っていますか？",
    help: "生命保険・介護医療保険・個人年金の保険料が対象です。3区分の合計で最大12万円まで控除できます。",
    document: "生命保険料控除証明書（秋〜冬に郵送）",
    amountLabel: "控除証明書の金額",
    placeholder: "例：80,000",
    icon: "shield",
  },
  {
    type: "jishin_hoken",
    label: "地震保険料控除",
    question: "地震保険に入っていますか？",
    help: "地震保険料は最大5万円まで控除できます。火災保険とセットの契約でも、地震保険部分が対象です。",
    document: "地震保険料控除証明書",
    amountLabel: "年間の保険料",
    placeholder: "例：30,000",
    icon: "shield",
  },
  {
    type: "ideco",
    label: "iDeCo・小規模企業共済",
    question: "iDeCoや小規模企業共済に加入していますか？",
    help: "iDeCo（個人型確定拠出年金）や小規模企業共済の掛金は、全額が控除の対象です。節税効果がとても大きい控除です。",
    document: "小規模企業共済等掛金払込証明書",
    amountLabel: "年間の掛金",
    placeholder: "例：276,000",
    icon: "box",
  },
  {
    type: "furusato",
    label: "ふるさと納税（寄附金控除）",
    question: "ふるさと納税をしましたか？",
    help: "確定申告をする場合、ワンストップ特例は無効になります。今年の寄附はすべて申告してください。寄附額から2,000円を引いた額が対象です。",
    document: "寄附金受領証明書（または XML 証明書）",
    amountLabel: "年間の寄附総額",
    placeholder: "例：50,000",
    icon: "sparkle",
  },
  {
    type: "iryohi",
    label: "医療費控除",
    question: "医療費は年間10万円を超えましたか？",
    help: "支払った医療費から保険などの補填を引いた額が、10万円（または所得の5%）を超えると控除できます。家族分も合算できます。",
    document: "医療費控除の明細書（領収書から集計）",
    amountLabel: "年間の医療費（支払総額）",
    placeholder: "例：180,000",
    icon: "receipt",
    hasReimbursement: true,
  },
  {
    type: "haigusha",
    label: "配偶者（特別）控除",
    question: "配偶者を扶養していますか？",
    help: "配偶者の所得に応じて、最大38万円（70歳以上は48万円）まで控除できます。あなたの所得が一定額を超えると対象外です。",
    document: "配偶者の所得がわかる書類",
    amountLabel: "控除額",
    placeholder: "例：380,000",
    icon: "home",
  },
  {
    type: "fuyo",
    label: "扶養控除",
    question: "16歳以上の扶養家族はいますか？",
    help: "子ども（16歳以上）や親などの扶養家族が対象です。一般38万円・特定（19〜22歳）63万円・老人48万円など、区分により金額が異なります。",
    document: "扶養家族の情報（年齢・続柄）",
    amountLabel: "扶養控除の合計額",
    placeholder: "例：380,000",
    icon: "home",
  },
];

/** Mapa rapido type -> paso (para resolver desde una sugerencia). */
export const STEP_BY_TYPE: Record<string, DeductionStep> = Object.fromEntries(
  DEDUCTION_STEPS.map((s) => [s.type, s]),
);

/**
 * Etiqueta japonesa por tipo de 控除 — incluye tipos que el backend persiste
 * pero NO son pasos del wizard (ej. `housing_loan` = 住宅ローン控除, que es
 * 税額控除 y se gestiona en la guía 更正の請求, no como 所得控除 interactivo).
 * La lista "登録済みの控除" usa esto para nunca mostrar el slug crudo.
 */
export const DEDUCTION_LABELS: Record<string, string> = {
  ...Object.fromEntries(DEDUCTION_STEPS.map((s) => [s.type, s.label])),
  kiso: "基礎控除",
  housing_loan: "住宅ローン控除",
  disability_self: "本人の障害者控除（一般）",
  other: "その他の控除",
};
