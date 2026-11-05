/**
 * Variants del 更正の請求ガイド: acordeon de pasos + check de la lista de
 * documentos. Tono "Calma fiscal": sereno, sin rebote. Reglas del repo: las
 * variants de Framer Motion viven FUERA del componente (archivos *Variants.ts).
 */
import type { Variants } from "framer-motion";

/** Cuerpo colapsable de un paso/sección de la guía (acordeon sereno). */
export const guideStepBodyVariants: Variants = {
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

/** Item de un checklist que entra escalonado desde abajo. */
export const checklistItemVariants: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] },
  },
};

/** Marca de "completado" (check) que asienta en celadon al tildarse. */
export const checkMarkVariants: Variants = {
  hidden: { scale: 0.6, opacity: 0 },
  visible: {
    scale: 1,
    opacity: 1,
    transition: { duration: 0.24, ease: [0.22, 1, 0.36, 1] },
  },
};
