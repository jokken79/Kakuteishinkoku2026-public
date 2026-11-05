/** Variants de Framer Motion del screen 提案・アドバイス (recomendaciones). */
import type { Variants } from "framer-motion";

/** Tarjeta de recomendacion: entra desde abajo, serena (sin rebote). */
export const recommendationCardVariants: Variants = {
  hidden: { opacity: 0, y: 14 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.38, ease: [0.22, 1, 0.36, 1] },
  },
};

/** Monto de ahorro (¥): "asienta" desde una escala leve al aparecer. */
export const savingAmountVariants: Variants = {
  hidden: { opacity: 0, scale: 0.94 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.42, ease: [0.22, 1, 0.36, 1], delay: 0.06 },
  },
};
