/**
 * Store de toasts (Zustand): micro-feedback de confirmacion discreto y sereno.
 * No usa 朱色 (reservado para el sello hanko): usa seiji (celadon) para exito y
 * sumi para informativo. Auto-descarta tras unos segundos.
 */
import { create } from "zustand";

/** Tono visual del toast. `success` = seiji (celadon); `info` = sumi. */
export type ToastTone = "success" | "info";

export interface Toast {
  id: number;
  /** Texto japones (documento oficial). */
  message: string;
  /** Glosa ES opcional (capa de ayuda; se muestra si helpEs esta activo). */
  es?: string;
  tone: ToastTone;
}

interface ToastState {
  toasts: Toast[];
  /** Encola un toast y devuelve su id (para descarte manual si hiciera falta). */
  push: (toast: Omit<Toast, "id">) => number;
  dismiss: (id: number) => void;
}

let _seq = 0;

/** Duracion por defecto del toast en pantalla (ms). Suficiente para leerlo sin
 * estorbar (discreto): se descarta solo, no pide accion. */
const TOAST_TTL_MS = 3200;

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  push: (toast) => {
    const id = ++_seq;
    set((state) => ({ toasts: [...state.toasts, { ...toast, id }] }));
    // Auto-descarte (sereno: no pide accion del usuario).
    if (typeof window !== "undefined") {
      window.setTimeout(() => get().dismiss(id), TOAST_TTL_MS);
    }
    return id;
  },
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

/**
 * Helper imperativo para emitir el toast de guardado ("保存しました / Guardado").
 * Centraliza el copy para que sea identico en todos los puntos de guardado.
 */
export function toastSaved(): void {
  useToastStore.getState().push({
    message: "保存しました",
    es: "Guardado",
    tone: "success",
  });
}
