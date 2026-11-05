/**
 * Variants del gesto del sello 印 (hanko) — el signature de la app.
 *
 * Al confirmar un 仕訳, el sello rojo shuiro se "estampa": baja con un settle,
 * deja la tinta asentar y rota levemente, como un 印鑑 real sobre papel.
 * `prefers-reduced-motion` se respeta a nivel CSS (index.css) y aqui via la
 * transicion instantanea cuando se pide.
 */
import type { Variants, Transition } from "framer-motion";

/** Sello que aparece sobre la tarjeta al confirmar (overlay efimero). */
export const hankoStampVariants: Variants = {
  hidden: {
    opacity: 0,
    scale: 1.55,
    rotate: -14,
  },
  stamp: {
    opacity: [0, 0.92, 1],
    scale: [1.55, 0.86, 1],
    rotate: [-14, -7, -5],
    transition: {
      duration: 0.42,
      times: [0, 0.55, 1],
      ease: [0.22, 1, 0.36, 1],
    },
  },
  settle: {
    opacity: 1,
    scale: 1,
    rotate: -5,
  },
};

/** Anillo de tinta que "respira" al asentar el sello. */
export const hankoInkVariants: Variants = {
  hidden: { opacity: 0, scale: 0.7 },
  stamp: {
    opacity: [0, 0.5, 0.32],
    scale: [0.7, 1.08, 1],
    transition: { duration: 0.5, ease: "easeOut" },
  },
};

/** La tarjeta retrocede un instante al recibir el sello (papel que cede). */
export const cardPressVariants: Variants = {
  rest: { scale: 1 },
  pressed: {
    scale: [1, 0.985, 1],
    transition: { duration: 0.42, ease: "easeInOut" },
  },
};

/** Transicion de salida de la tarjeta confirmada (sale de la bandeja). */
export const cardExitTransition: Transition = {
  duration: 0.34,
  ease: [0.4, 0, 1, 1],
};
