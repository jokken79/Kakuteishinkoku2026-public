/**
 * Variants del onboarding guiado. Animaciones serenas ("Calma fiscal"): un
 * paso entra/sale con un fade + leve desplazamiento, sin rebote. Respeta
 * `prefers-reduced-motion` via `MotionConfig reducedMotion="user"` (global).
 */
import type { Variants } from "framer-motion";

/** Overlay del onboarding: fade suave del fondo. */
export const onboardingOverlayVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.35, ease: [0.22, 1, 0.36, 1] } },
  exit: { opacity: 0, transition: { duration: 0.3, ease: [0.4, 0, 1, 1] } },
};

/**
 * Un paso del onboarding. La direccion (`1` adelante, `-1` atras) determina el
 * sentido del desplazamiento horizontal (sensacion de "avanzar"/"volver").
 */
export const onboardingStepVariants: Variants = {
  enter: (dir: number) => ({
    opacity: 0,
    x: dir >= 0 ? 28 : -28,
  }),
  center: {
    opacity: 1,
    x: 0,
    transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] },
  },
  exit: (dir: number) => ({
    opacity: 0,
    x: dir >= 0 ? -28 : 28,
    transition: { duration: 0.28, ease: [0.4, 0, 1, 1] },
  }),
};

/** Tarjeta de opcion (申告区分, 消費税): leve subida escalonada. */
export const onboardingOptionVariants: Variants = {
  hidden: { opacity: 0, y: 10 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.32, ease: [0.22, 1, 0.36, 1] },
  },
};
