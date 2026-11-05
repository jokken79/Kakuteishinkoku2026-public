/**
 * Store de UI (Zustand): seccion activa de navegacion + ayuda en castellano +
 * 年度 activo del ciclo multi-año fiscal.
 */
import { create } from "zustand";

/** Clave de localStorage para persistir la preferencia de ayuda ES. */
const HELP_ES_KEY = "kakutei.helpEs";

/** Clave de localStorage para persistir el 年度 activo entre sesiones. */
const ACTIVE_YEAR_KEY = "kakutei.activeYear";

/**
 * Año fiscal de arranque cuando aún no se cargó la lista de 年度 del backend
 * (令和7 = 2025). El selector lo reemplaza por el año OPEN más reciente en
 * cuanto `GET /fiscal-years` responde, así la experiencia actual (solo 2025)
 * no cambia.
 */
export const DEFAULT_ACTIVE_YEAR = 2025;

/** Lee el 年度 activo persistido, o el default si no hay ninguno guardado. */
function readActiveYear(): number {
  if (typeof window === "undefined") return DEFAULT_ACTIVE_YEAR;
  try {
    const raw = window.localStorage.getItem(ACTIVE_YEAR_KEY);
    if (raw === null) return DEFAULT_ACTIVE_YEAR;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) ? parsed : DEFAULT_ACTIVE_YEAR;
  } catch {
    return DEFAULT_ACTIVE_YEAR;
  }
}

/** Persiste el 年度 activo (silencioso si localStorage falla). */
function writeActiveYear(year: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ACTIVE_YEAR_KEY, String(year));
  } catch {
    /* almacenamiento no disponible: la preferencia vive solo en memoria */
  }
}

/**
 * Lee la preferencia de ayuda ES persistida. Default: `true` (el owner es
 * hispanohablante y la necesita), pero conmutable y recordada entre sesiones.
 */
function readHelpEs(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(HELP_ES_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

/** Persiste la preferencia de ayuda ES (silencioso si localStorage falla). */
function writeHelpEs(value: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(HELP_ES_KEY, value ? "1" : "0");
  } catch {
    /* almacenamiento no disponible: la preferencia vive solo en memoria */
  }
}

interface UiState {
  /** Id de la seccion de navegacion activa. */
  activeSection: string;
  setActiveSection: (id: string) => void;
  /**
   * Si la capa de ayuda en castellano esta activa. La UI sigue en japones
   * (documento oficial); esto solo agrega glosas/subtitulos ES discretos.
   */
  helpEs: boolean;
  setHelpEs: (value: boolean) => void;
  toggleHelpEs: () => void;
  /**
   * 年度 activo del ciclo multi-año fiscal. Todos los hooks de datos (控除/収入/
   * filing/受領/...) leen este valor: al cambiarlo, la app entera refleja ese año.
   * Persistido en localStorage; arranca en `DEFAULT_ACTIVE_YEAR` y el selector lo
   * sincroniza con el año OPEN más reciente del backend.
   */
  activeYear: number;
  setActiveYear: (year: number) => void;
}

export const useUiStore = create<UiState>((set) => ({
  activeSection: "dashboard",
  setActiveSection: (id) => set({ activeSection: id }),
  helpEs: readHelpEs(),
  setHelpEs: (value) => {
    writeHelpEs(value);
    set({ helpEs: value });
  },
  toggleHelpEs: () =>
    set((state) => {
      const next = !state.helpEs;
      writeHelpEs(next);
      return { helpEs: next };
    }),
  activeYear: readActiveYear(),
  setActiveYear: (year) => {
    writeActiveYear(year);
    set({ activeYear: year });
  },
}));

/** Hook utilitario: respeta prefers-reduced-motion para gestos opcionales. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
