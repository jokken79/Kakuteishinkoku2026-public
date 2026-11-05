/** Utilidades de formato del dominio (montos ¥, fechas 和暦, 勘定科目). */

/** Formatea un entero de yenes como `¥1,234` (sin decimales). */
export function formatYen(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "¥—";
  const sign = amount < 0 ? "−" : "";
  return `${sign}¥${Math.abs(amount).toLocaleString("ja-JP")}`;
}

/** Formatea un monto sin el simbolo ¥ (para cuando el ¥ se renderiza aparte). */
export function formatAmount(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  return Math.abs(amount).toLocaleString("ja-JP");
}

/** Convierte un anio gregoriano a 令和 (令和 = 2018-base). */
export function toReiwa(year: number): string {
  return `令和${year - 2018}年`;
}

/** Formatea una fecha ISO (`2025-06-14`) como `2025/06/14`. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.replaceAll("-", "/");
}

/** Mapa de codigo de cuenta -> 勘定科目 (espejo del seed del backend). */
export const ACCOUNT_NAMES: Record<string, string> = {
  "101": "現金",
  "102": "普通預金",
  "135": "売掛金",
  "201": "買掛金",
  "205": "未払金",
  "301": "元入金",
  "311": "事業主貸",
  "312": "事業主借",
  "401": "売上高",
  "409": "雑収入",
  "501": "旅費交通費",
  "502": "消耗品費",
  "503": "接待交際費",
  "504": "会議費",
  "505": "通信費",
  "506": "新聞図書費",
  "507": "地代家賃",
  "508": "水道光熱費",
  "509": "広告宣伝費",
  "510": "支払手数料",
  "511": "租税公課",
  "512": "減価償却費",
  "513": "外注工賃",
  "599": "雑費",
};

/** 勘定科目 sugeribles para edicion inline en la bandeja (subset frecuente). */
export const EXPENSE_ACCOUNTS: { code: string; name: string }[] = [
  { code: "501", name: "旅費交通費" },
  { code: "502", name: "消耗品費" },
  { code: "503", name: "接待交際費" },
  { code: "504", name: "会議費" },
  { code: "505", name: "通信費" },
  { code: "506", name: "新聞図書費" },
  { code: "507", name: "地代家賃" },
  { code: "508", name: "水道光熱費" },
  { code: "509", name: "広告宣伝費" },
  { code: "510", name: "支払手数料" },
  { code: "511", name: "租税公課" },
  { code: "512", name: "減価償却費" },
  { code: "599", name: "雑費" },
];

export function accountName(code: string | null | undefined): string {
  if (!code) return "未分類";
  return ACCOUNT_NAMES[code] ?? code;
}

/** Nivel de confianza derivado del score (umbral 0.75 = backend). */
export function confidenceLevel(score: number | null | undefined): "high" | "low" {
  return (score ?? 0) >= 0.75 ? "high" : "low";
}

/** Score 0-1 -> porcentaje entero legible. */
export function confidencePct(score: number | null | undefined): number {
  return Math.round((score ?? 0) * 100);
}

/** Etiqueta japonesa de "que revisar" por campo dudoso del OCR. */
const FIELD_REVIEW_HINTS: Record<string, string> = {
  total: "金額を確認",
  vendor: "店名を確認",
  date: "日付が不明瞭",
  tax_lines: "税率を確認",
  registration_number: "登録番号を確認",
};

/**
 * Deriva el hint de "que revisar" para un recibo de baja confianza.
 *
 * Prefiere el campo con menor confianza de `field_confidences` (si el backend
 * lo provee). Si no hay datos por campo, cae a un hint generico. Devuelve
 * ``null`` cuando el recibo es de alta confianza (no necesita aviso).
 */
export function reviewHint(
  fieldConfidences: Record<string, number> | null | undefined,
  overall: number | null | undefined,
): string | null {
  if (confidenceLevel(overall) === "high") return null;
  if (fieldConfidences) {
    let weakest: string | null = null;
    let min = Infinity;
    for (const [field, conf] of Object.entries(fieldConfidences)) {
      // Ignora campos ausentes legitimamente (ej. registro 0 = no aplica).
      if (conf <= 0) continue;
      if (conf < min) {
        min = conf;
        weakest = field;
      }
    }
    if (weakest && min < 0.75 && FIELD_REVIEW_HINTS[weakest]) {
      return FIELD_REVIEW_HINTS[weakest];
    }
  }
  return "内容を確認してください";
}

/** Categoria visual del 勘定科目 para elegir el glifo del thumbnail. */
export type AccountCategory =
  | "travel"
  | "comm"
  | "supplies"
  | "meeting"
  | "entertain"
  | "books"
  | "utility"
  | "generic";

/** Mapea un codigo de 勘定科目 a una categoria visual (icono del recibo). */
export function accountCategory(code: string | null | undefined): AccountCategory {
  switch (code) {
    case "501":
      return "travel"; // 旅費交通費
    case "505":
      return "comm"; // 通信費
    case "502":
      return "supplies"; // 消耗品費
    case "504":
      return "meeting"; // 会議費
    case "503":
      return "entertain"; // 接待交際費
    case "506":
      return "books"; // 新聞図書費
    case "508":
      return "utility"; // 水道光熱費
    default:
      return "generic";
  }
}

/** Dias restantes hasta una fecha objetivo (medianoche local para evitar TZ). */
export function daysUntil(target: Date): number {
  const now = new Date();
  const a = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const b = new Date(target.getFullYear(), target.getMonth(), target.getDate());
  return Math.round((b.getTime() - a.getTime()) / 86_400_000);
}

/**
 * Plazo ordinario: 15 de marzo del año siguiente, prorrogado al lunes si cae
 * en fin de semana. No contempla ampliaciones extraordinarias o festivos nuevos.
 *
 * @param year - Año fiscal (西暦, ej. 2025).
 * @returns Fecha ordinaria estimada de presentación.
 */
export function filingDeadlineForYear(year: number): Date {
  const deadline = new Date(year + 1, 2, 15);
  if (deadline.getDay() === 6) deadline.setDate(17);
  if (deadline.getDay() === 0) deadline.setDate(16);
  return deadline;
}
