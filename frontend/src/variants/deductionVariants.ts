/** Variants del 控除ウィザード: acordeon de pasos, 節税額 que aparece, sugerencias. */
import type { Variants } from "framer-motion";

/** Cuerpo colapsable de un paso del wizard (acordeon sereno, sin rebote). */
export const stepBodyVariants: Variants = {
  collapsed: {
    height: 0,
    opacity: 0,
    transition: { duration: 0.28, ease: [0.22, 1, 0.36, 1] },
  },
  expanded: {
    height: "auto",
    opacity: 1,
    transition: { duration: 0.34, ease: [0.22, 1, 0.36, 1] },
  },
};

/** Badge de 節税額 (ahorro) que "asienta" en celadon al guardarse. */
export const savingBadgeVariants: Variants = {
  hidden: { opacity: 0, scale: 0.9, y: 4 },
  visible: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] },
  },
};

/** Pulso suave del impuesto del header cuando cambia (feedback "bajó"). */
export const taxPulseVariants: Variants = {
  idle: { scale: 1 },
  pulse: {
    scale: [1, 1.04, 1],
    transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] },
  },
};

/** Tarjeta de sugerencia (entra desde abajo, escalonada por el contenedor). */
export const suggestionVariants: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.34, ease: [0.22, 1, 0.36, 1] },
  },
};
