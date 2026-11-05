/**
 * Variants para el bottom sheet "もっと" de la nav móvil.
 * Diseño "Calma fiscal": entrada serena desde abajo, sin rebote agresivo.
 */
import type { Variants } from "framer-motion";

/** Overlay semitransparente que bloquea el fondo mientras el sheet está abierto. */
export const moreSheetOverlayVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] },
  },
  exit: {
    opacity: 0,
    transition: { duration: 0.18, ease: [0.4, 0, 1, 1] },
  },
};

/** Panel del sheet: desliza desde el borde inferior. */
export const moreSheetPanelVariants: Variants = {
  hidden: { y: "100%" },
  visible: {
    y: 0,
    transition: { duration: 0.32, ease: [0.22, 1, 0.36, 1] },
  },
  exit: {
    y: "100%",
    transition: { duration: 0.22, ease: [0.4, 0, 1, 1] },
  },
};

/** Lista de ítems: escalonado suave para reforzar la serenidad. */
export const moreSheetListVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.045, delayChildren: 0.1 },
  },
};

/** Cada ítem de la lista en el sheet. */
export const moreSheetItemVariants: Variants = {
  hidden: { opacity: 0, x: -8 },
  visible: {
    opacity: 1,
    x: 0,
    transition: { duration: 0.24, ease: [0.22, 1, 0.36, 1] },
  },
};
