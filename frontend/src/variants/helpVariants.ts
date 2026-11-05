/** Variants del popover de ayuda ES: aparicion serena, sin rebote ni ruido. */
import type { Variants } from "framer-motion";

/**
 * Popover/tooltip de glosa en castellano. Entrada suave (fade + leve subida);
 * prefers-reduced-motion lo neutraliza via la regla global de index.css.
 */
export const helpPopoverVariants: Variants = {
  hidden: { opacity: 0, y: 4, scale: 0.98 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.16, ease: [0.22, 1, 0.36, 1] },
  },
  exit: {
    opacity: 0,
    y: 4,
    scale: 0.98,
    transition: { duration: 0.12, ease: [0.4, 0, 1, 1] },
  },
};
