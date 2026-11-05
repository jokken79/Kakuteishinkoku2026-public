/**
 * Catálogo de CATEGORÍAS AMIGABLES de gastos del NEGOCIO (capa de presentación).
 *
 * Cada categoría amigable mapea 1:1 a un 勘定科目 contable existente (ver el seed
 * del backend `app/seed/accounts.py`). NO cambia el modelo contable: es solo UX
 * para que el 個人事業主 elija "🚃 交通費" en vez de pensar en "旅費交通費 (501)".
 * Al elegir una categoría se persiste el `accountCode` real (el 勘定科目).
 */

/** Una categoría amigable de gasto del negocio (espejo de un 勘定科目). */
export interface ExpenseCategory {
  /** Id estable en inglés. */
  readonly id: string;
  /** Emoji representativo (selector visual). */
  readonly emoji: string;
  /** Etiqueta japonesa amigable (UI). */
  readonly labelJa: string;
  /** Glosa en castellano (capa de ayuda ES). */
  readonly labelEs: string;
  /** Código del 勘定科目 real al que mapea (lo que se persiste). */
  readonly accountCode: string;
}

/**
 * Categorías amigables, una por cada 勘定科目 de gasto (5xx) del seed. El orden
 * es el de uso frecuente esperado (交通・消耗品 arriba, その他 al final).
 */
export const EXPENSE_CATEGORIES: readonly ExpenseCategory[] = [
  { id: "transport", emoji: "🚃", labelJa: "交通費", labelEs: "Transporte", accountCode: "501" },
  { id: "supplies", emoji: "🛒", labelJa: "消耗品・備品", labelEs: "Consumibles", accountCode: "502" },
  { id: "entertain", emoji: "🍽", labelJa: "接待・交際", labelEs: "Comidas / atenciones", accountCode: "503" },
  { id: "meeting", emoji: "📋", labelJa: "会議", labelEs: "Reuniones", accountCode: "504" },
  { id: "comm", emoji: "📱", labelJa: "通信", labelEs: "Comunicaciones", accountCode: "505" },
  { id: "books", emoji: "📖", labelJa: "新聞図書", labelEs: "Prensa / libros", accountCode: "506" },
  { id: "rent", emoji: "🏠", labelJa: "家賃・地代", labelEs: "Alquiler", accountCode: "507" },
  { id: "utility", emoji: "💡", labelJa: "水道光熱", labelEs: "Suministros", accountCode: "508" },
  { id: "ads", emoji: "📢", labelJa: "広告", labelEs: "Publicidad", accountCode: "509" },
  { id: "fees", emoji: "💳", labelJa: "支払手数料", labelEs: "Comisiones", accountCode: "510" },
  { id: "tax", emoji: "🧾", labelJa: "税金", labelEs: "Impuestos / tasas", accountCode: "511" },
  { id: "insurance", emoji: "🛡", labelJa: "損害保険", labelEs: "Seguros", accountCode: "514" },
  { id: "other", emoji: "📦", labelJa: "その他", labelEs: "Otros", accountCode: "599" },
] as const;

/** Índice accountCode -> categoría amigable (para resolver el 勘定科目 elegido). */
const BY_CODE: Readonly<Record<string, ExpenseCategory>> = Object.fromEntries(
  EXPENSE_CATEGORIES.map((c) => [c.accountCode, c]),
);

/**
 * Devuelve la categoría amigable de un 勘定科目. Si el código no tiene categoría
 * dedicada (ej. 512 減価償却費, que no se captura como gasto manual de recibo),
 * cae a "その他" (599) para que el selector siempre tenga una opción válida.
 */
export function categoryForAccount(
  code: string | null | undefined,
): ExpenseCategory {
  if (code && BY_CODE[code]) return BY_CODE[code];
  return BY_CODE["599"];
}
