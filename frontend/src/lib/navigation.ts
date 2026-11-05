/** Definición de la navegación por el flujo real de una declaración. */

export type NavGroupId = "start" | "records" | "filing" | "history" | "other";

export interface NavSection {
  readonly id: string;
  readonly group: NavGroupId;
  readonly label: string;
  readonly short: string;
  readonly icon: string;
  readonly description: string;
  readonly es: string;
  readonly ready: boolean;
}

export const NAV_GROUPS: readonly {
  id: NavGroupId;
  label: string;
  es: string;
}[] = [
  { id: "start", label: "はじめに", es: "Inicio" },
  { id: "records", label: "記録・帳簿", es: "Registros" },
  { id: "filing", label: "申告", es: "Declaración" },
  { id: "history", label: "申告後", es: "Después" },
  { id: "other", label: "その他", es: "Otros" },
];

export const NAV_SECTIONS: readonly NavSection[] = [
  {
    id: "dashboard",
    group: "start",
    label: "ダッシュボード",
    short: "ホーム",
    icon: "home",
    description: "今年の概要・推定税額・進捗",
    es: "Panel",
    ready: true,
  },
  {
    id: "recommendations",
    group: "start",
    label: "提案・アドバイス",
    short: "提案",
    icon: "sparkle",
    description: "節税のヒントを優先度順に提案",
    es: "Recomendaciones",
    ready: true,
  },
  {
    id: "capture",
    group: "records",
    label: "撮影",
    short: "撮影",
    icon: "camera",
    description: "領収書を撮影・アップロード",
    es: "Capturar",
    ready: true,
  },
  {
    id: "import",
    group: "records",
    label: "取り込み",
    short: "取込",
    icon: "archive",
    description: "銀行・カードの明細CSVから仕訳を作成",
    es: "Importar CSV",
    ready: true,
  },
  {
    id: "journal-tray",
    group: "records",
    label: "仕訳トレイ",
    short: "仕訳",
    icon: "tray",
    description: "提案された仕訳を確認・承認",
    es: "Asientos",
    ready: true,
  },
  {
    id: "income",
    group: "records",
    label: "収入",
    short: "収入",
    icon: "signal",
    description: "売上・給与・源泉徴収を入力",
    es: "Ingresos",
    ready: true,
  },
  {
    id: "sales-documents",
    group: "records",
    label: "売上・請求",
    short: "請求",
    icon: "file",
    description: "見積書・請求書・領収書を作成",
    es: "見積・請求・領収",
    ready: true,
  },
  {
    id: "books",
    group: "records",
    label: "帳簿",
    short: "帳簿",
    icon: "book",
    description: "仕訳帳・総勘定元帳を確認・出力",
    es: "Libros",
    ready: true,
  },
  {
    id: "evidence",
    group: "records",
    label: "領収書・証明書",
    short: "書類",
    icon: "receipt",
    description: "領収書や証明書を日付・金額・取引先で検索",
    es: "Comprobantes",
    ready: true,
  },
  {
    id: "remittances",
    group: "records",
    label: "海外送金",
    short: "送金",
    icon: "file",
    description: "ブラジルなどへの送金準備と証明書の確認",
    es: "Remesas y Brasil",
    ready: true,
  },
  {
    id: "deduction-wizard",
    group: "filing",
    label: "控除ウィザード",
    short: "控除",
    icon: "compass",
    description: "質問に答えるだけで控除を登録",
    es: "Deducciones",
    ready: true,
  },
  {
    id: "consumption",
    group: "filing",
    label: "消費税",
    short: "消費税",
    icon: "box",
    description: "本則・簡易・2割特例を比較",
    es: "IVA japonés",
    ready: true,
  },
  {
    id: "filing",
    group: "filing",
    label: "確定申告",
    short: "申告",
    icon: "file",
    description: "申告書の生成（PDF / .xtx / CSV）",
    es: "Declaración",
    ready: true,
  },
  {
    id: "year-end",
    group: "filing",
    label: "年末調整",
    short: "年末調整",
    icon: "file",
    description: "扶養と障害者控除の書類を準備",
    es: "Ajuste de fin de año",
    ready: true,
  },
  {
    id: "past-filings",
    group: "history",
    label: "過去の申告",
    short: "過去",
    icon: "calendar",
    description: "過去の申告書を保存・年度比較",
    es: "Declaraciones anteriores",
    ready: true,
  },
  {
    id: "kosei-seikyu",
    group: "history",
    label: "更正の請求ガイド",
    short: "更正",
    icon: "compass",
    description: "控除を取り戻す手順ガイド",
    es: "Guía de corrección",
    ready: true,
  },
  {
    id: "kakebo",
    group: "other",
    label: "家計簿",
    short: "家計",
    icon: "book",
    description: "申告に含まれない個人支出を記録",
    es: "Gastos personales",
    ready: true,
  },
  {
    id: "settings",
    group: "other",
    label: "設定",
    short: "設定",
    icon: "gear",
    description: "プロフィール・申告区分・OCR",
    es: "Ajustes",
    ready: true,
  },
] as const;

/** Barra inferior móvil: cinco tareas principales; el resto vive en もっと. */
export const MOBILE_PRIMARY_IDS = [
  "dashboard",
  "capture",
  "journal-tray",
  "deduction-wizard",
  "filing",
] as const;

/** @deprecated Usar MOBILE_PRIMARY_IDS + MobileMoreSheet. */
export const MOBILE_NAV_IDS = [
  "dashboard",
  "recommendations",
  "journal-tray",
  "income",
  "deduction-wizard",
  "filing",
  "consumption",
  "settings",
];
