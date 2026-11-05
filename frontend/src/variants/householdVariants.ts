/** Variants de Framer Motion del 家計簿 (selector de 費目 + filas de gastos). */
import type { Variants } from "framer-motion";

/** Botón de 費目 del selector visual: micro press al tocar. */
export const categoryPickVariants: Variants = {
  rest: { scale: 1 },
  tap: { scale: 0.94 },
};

/** Fila de gasto en la lista: entra desde abajo, sale a la derecha al borrar. */
export const expenseRowVariants: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.28, ease: [0.22, 1, 0.36, 1] },
  },
  exit: {
    opacity: 0,
    x: 32,
    transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] },
  },
};
