/** Variants del dropdown del selector de 年度: aparicion serena (Calma fiscal). */
import type { Variants } from "framer-motion";

/**
 * Menú desplegable del selector de año. Entrada suave (fade + leve subida y
 * escala), sin rebote: coherente con el resto de popovers de la app.
 * prefers-reduced-motion lo neutraliza via la regla global de index.css.
 */
export const yearMenuVariants: Variants = {
  hidden: { opacity: 0, y: -4, scale: 0.98 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.16, ease: [0.22, 1, 0.36, 1] },
  },
  exit: {
    opacity: 0,
    y: -4,
    scale: 0.98,
    transition: { duration: 0.12, ease: [0.4, 0, 1, 1] },
  },
};
