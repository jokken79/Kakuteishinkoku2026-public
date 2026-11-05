/** Catalogo de tipos de 収入 (ingresos) editables del owner — UI japones. */
import type { IconName } from "../components/Icon";
import type { IncomeType } from "./api";

/** Definicion de un tipo de ingreso para la pantalla 収入. */
export interface IncomeKindDef {
  /** Tipo de 所得 (enum `IncomeType`). */
  readonly type: IncomeType;
  /** Etiqueta visible en japones. */
  readonly label: string;
  /** Termino del glosario para la capa de ayuda ES. */
  readonly term: string;
  /** Pregunta / descripcion corta conversacional. */
  readonly question: string;
  /** Ayuda contextual (que documento, como se calcula). */
  readonly help: string;
  /** Etiqueta del campo principal (収入金額 / 売上). */
  readonly grossLabel: string;
  /** Placeholder del monto principal. */
  readonly placeholder: string;
  /** Si expone el campo 源泉徴収税額 (給与/報酬 lo tienen). */
  readonly hasWithholding: boolean;
  /** Si expone el campo 必要経費 (雑/不動産 lo tienen; jigyo NO: viene de 仕訳). */
  readonly hasExpenses: boolean;
  /** Icono line-art. */
  readonly icon: IconName;
  /** `true` si es un tipo nucleo (siempre visible); `false` = opcional (se agrega). */
  readonly core: boolean;
}

export const INCOME_KINDS: readonly IncomeKindDef[] = [
  {
    type: "jigyo",
    label: "事業収入（売上）",
    term: "売上",
    question: "今年の事業の売上はいくらでしたか？",
    help: "自営業・フリーランスの年間売上（経費を引く前の総収入）です。経費は「仕訳トレイ」で確認した分が自動で差し引かれます。",
    grossLabel: "年間の売上金額",
    placeholder: "例：6,800,000",
    hasWithholding: false,
    hasExpenses: false,
    icon: "signal",
    core: true,
  },
  {
    type: "kyuyo",
    label: "給与収入",
    term: "給与所得",
    question: "給与（アルバイト・パート含む）はありましたか？",
    help: "勤務先からの給与収入と、源泉徴収票に記載された源泉徴収税額を入力します。源泉徴収税額は納付額から差し引かれます。",
    grossLabel: "給与の収入金額",
    placeholder: "例：0",
    hasWithholding: true,
    hasExpenses: false,
    icon: "receipt",
    core: true,
  },
  {
    type: "zatsu",
    label: "雑所得",
    term: "雑所得",
    question: "副業・暗号資産などの雑所得はありましたか？",
    help: "他の区分に当てはまらない収入。公的年金等控除や分離課税の所得はこの計算では対応していません。公的年金や特殊な取引がある場合は税務署等で確認してください。",
    grossLabel: "雑所得の収入金額",
    placeholder: "例：200,000",
    hasWithholding: true,
    hasExpenses: true,
    icon: "box",
    core: false,
  },
  {
    type: "fudosan",
    label: "不動産所得",
    term: "事業所得",
    question: "家賃収入などの不動産所得はありましたか？",
    help: "土地・建物の貸付による収入。収入から必要経費（管理費・固定資産税など）を引いた額が所得になります。",
    grossLabel: "不動産の収入金額",
    placeholder: "例：0",
    hasWithholding: false,
    hasExpenses: true,
    icon: "book",
    core: false,
  },
];

/** Etiqueta ES corta para el subtitulo de cada tipo (capa de ayuda). */
export const INCOME_ES_LABEL: Readonly<Record<IncomeType, string>> = {
  jigyo: "Ingresos del negocio (ventas)",
  kyuyo: "Salario y retención en origen",
  zatsu: "Otros ingresos (varios)",
  fudosan: "Ingresos inmobiliarios",
};

export const INCOME_KIND_BY_TYPE: Readonly<Record<string, IncomeKindDef>> =
  Object.fromEntries(INCOME_KINDS.map((k) => [k.type, k]));
