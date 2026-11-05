/**
 * Catálogo de 費目 del 家計簿 (libro de gastos PERSONALES, NO fiscal).
 *
 * Espejo del enum `HouseholdCategory` del backend. Cada 費目 lleva un emoji para
 * el selector visual. NO tiene relación con los 勘定科目 contables del negocio:
 * el 家計簿 trackea gastos del hogar que NO entran a la declaración.
 */

/** Id de 費目 — debe coincidir 1:1 con el enum `HouseholdCategory` del backend. */
export type HouseholdCategoryId =
  | "shokuhi"
  | "nichiyohin"
  | "jukyohi"
  | "suidokonetsu"
  | "kotsuhi"
  | "tsushinhi"
  | "kosaihi"
  | "gorakuhi"
  | "iryohi"
  | "ifuku"
  | "kyoiku"
  | "sonota";

/** Una categoría 費目 del 家計簿. */
export interface HouseholdCategory {
  /** Id estable (== value del enum backend). */
  readonly id: HouseholdCategoryId;
  /** Emoji representativo (selector visual). */
  readonly emoji: string;
  /** Etiqueta japonesa (UI). */
  readonly labelJa: string;
  /** Glosa en castellano (capa de ayuda ES). */
  readonly labelEs: string;
}

/** Las 12 categorías 家計簿 estándar (ざっくり), en orden de uso frecuente. */
export const HOUSEHOLD_CATEGORIES: readonly HouseholdCategory[] = [
  { id: "shokuhi", emoji: "🍙", labelJa: "食費", labelEs: "Comida" },
  { id: "nichiyohin", emoji: "🧴", labelJa: "日用品", labelEs: "Artículos del hogar" },
  { id: "jukyohi", emoji: "🏠", labelJa: "住居費", labelEs: "Vivienda" },
  { id: "suidokonetsu", emoji: "💡", labelJa: "水道光熱費", labelEs: "Agua / luz / gas" },
  { id: "kotsuhi", emoji: "🚃", labelJa: "交通費", labelEs: "Transporte" },
  { id: "tsushinhi", emoji: "📱", labelJa: "通信費", labelEs: "Comunicaciones" },
  { id: "kosaihi", emoji: "🍻", labelJa: "交際費", labelEs: "Vida social" },
  { id: "gorakuhi", emoji: "🎮", labelJa: "娯楽費", labelEs: "Ocio" },
  { id: "iryohi", emoji: "💊", labelJa: "医療費", labelEs: "Salud" },
  { id: "ifuku", emoji: "👕", labelJa: "衣服", labelEs: "Ropa" },
  { id: "kyoiku", emoji: "📚", labelJa: "教育", labelEs: "Educación" },
  { id: "sonota", emoji: "📦", labelJa: "その他", labelEs: "Otros" },
] as const;

/** Índice id -> 費目 (para resolver una categoría persistida). */
const BY_ID: Readonly<Record<string, HouseholdCategory>> = Object.fromEntries(
  HOUSEHOLD_CATEGORIES.map((c) => [c.id, c]),
);

/**
 * Devuelve el 費目 por id. Si el id es desconocido (datos viejos), cae a "その他"
 * para que la UI nunca muestre un valor crudo o `undefined`.
 */
export function householdCategory(
  id: string | null | undefined,
): HouseholdCategory {
  if (id && BY_ID[id]) return BY_ID[id];
  return BY_ID["sonota"];
}

/** Color de la rebanada del gráfico por 費目 (paleta serena, estable por id). */
export const HOUSEHOLD_CATEGORY_COLORS: Readonly<Record<HouseholdCategoryId, string>> = {
  shokuhi: "#dda24a", // kohaku
  nichiyohin: "#3e9b86", // seiji
  jukyohi: "#5a6175", // sumi-soft
  suidokonetsu: "#7cb6a6",
  kotsuhi: "#c98a4b",
  tsushinhi: "#8a91a5",
  kosaihi: "#d49a6a",
  gorakuhi: "#5fa890",
  iryohi: "#b06b6b",
  ifuku: "#9b8ab0",
  kyoiku: "#6b91b0",
  sonota: "#b8b2a6",
};
