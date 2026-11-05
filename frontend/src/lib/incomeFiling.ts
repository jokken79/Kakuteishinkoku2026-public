/**
 * Catálogos del onboarding/settings para el 申告区分 (filing type) y el 税務署
 * (提出先). UI en japonés + ayuda ES (capa de ayuda). Las claves (`value`) son
 * estables y espejan el backend (`FilingType` enum / `filing_office` key).
 */

/** 申告区分 — modalidad de declaración (espejo del enum `FilingType`). */
export type FilingType = "aoiro_65" | "aoiro_55" | "aoiro_10" | "shiroiro";

/** Opción de 申告区分 para el selector del onboarding/settings. */
export interface FilingTypeOption {
  readonly value: FilingType;
  /** Etiqueta visible en japonés. */
  readonly label: string;
  /** Etiqueta/explicación corta en castellano (capa de ayuda). */
  readonly es: string;
  /** Ayuda contextual en japonés (qué deducción da, qué requiere). */
  readonly help: string;
}

export const FILING_TYPE_OPTIONS: readonly FilingTypeOption[] = [
  {
    value: "aoiro_65",
    label: "青色申告（最大65万円控除）",
    es: "Hasta ¥650.000 si se cumplen los requisitos de ¥550.000 y los requisitos adicionales de e-Tax o libros electrónicos cualificados.",
    help: "55万円控除の要件に加え、期限内のe-Tax申告または優良な電子帳簿保存などの要件があります。",
  },
  {
    value: "aoiro_55",
    label: "青色申告（最大55万円控除）",
    es: "Hasta ¥550.000 con los requisitos de contabilidad, documentos y presentación dentro del plazo.",
    help: "正規の簿記、貸借対照表・損益計算書の添付、期限内申告などの要件があります。",
  },
  {
    value: "aoiro_10",
    label: "青色申告（最大10万円控除）",
    es: "Hasta ¥100.000 si se cumplen las condiciones de 青色申告 y no se aplica la deducción superior.",
    help: "青色申告の承認などの要件を満たし、55万円・65万円控除を受けない場合の区分です。",
  },
  {
    value: "shiroiro",
    label: "白色申告",
    es: "Declaración blanca: sin deducción especial de 青色申告; también requiere registros y conservación de documentos.",
    help: "青色申告特別控除はありません。記帳や書類保存は必要です。",
  },
];

/** Opción de 税務署 (提出先) para el selector. */
export interface OfficeOption {
  /** Clave estable (`filing_office`), ej. "tsushima". */
  readonly value: string;
  /** Etiqueta visible (nombre del 税務署). */
  readonly label: string;
  /** Nota corta (管轄 / referencia). */
  readonly note: string;
}

/**
 * 税務署 comunes. Solo 津島 está confirmado en el research del backend; el resto
 * son referencias frecuentes. Si el del usuario no está, hay un input libre.
 */
export const OFFICE_OPTIONS: readonly OfficeOption[] = [
  {
    value: "tsushima",
    label: "津島税務署",
    note: "津島市・愛西市・弥富市・あま市・海部郡（名古屋国税局）",
  },
  {
    value: "nagoya-naka",
    label: "名古屋中税務署",
    note: "名古屋市中区など（名古屋国税局）",
  },
  {
    value: "shinjuku",
    label: "新宿税務署",
    note: "東京都新宿区（東京国税局）",
  },
];
