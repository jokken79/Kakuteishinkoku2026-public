/**
 * Viewport de toasts: pila discreta abajo-centro. Sereno, sin 朱色 (reservado al
 * sello). Exito = seiji (celadon); info = sumi. Respeta la ayuda ES (glosa) y se
 * eleva sobre la bottom-nav en movil para no taparla.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useToastStore } from "../../lib/toast";
import { useUiStore } from "../../lib/store";
import { Icon } from "../Icon";
import { toastVariants } from "../../variants/layoutVariants";

export function ToastViewport() {
  const toasts = useToastStore((s) => s.toasts);
  const helpEs = useUiStore((s) => s.helpEs);

  return (
    <div
      aria-live="polite"
      role="status"
      className="pointer-events-none fixed inset-x-0 bottom-[calc(58px+env(safe-area-inset-bottom)+12px)] z-40 flex flex-col items-center gap-2 px-4 lg:bottom-6"
    >
      <AnimatePresence>
        {toasts.map((toast) => {
          const isSuccess = toast.tone === "success";
          return (
            <motion.div
              key={toast.id}
              layout
              variants={toastVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="pointer-events-auto flex items-center gap-2.5 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-4 py-2.5 shadow-[var(--shadow-lift)]"
            >
              <span
                className={`grid h-5 w-5 shrink-0 place-items-center rounded-full ${
                  isSuccess
                    ? "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]"
                    : "bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]"
                }`}
              >
                <Icon name="check" className="h-3 w-3" />
              </span>
              <span className="text-sm font-medium text-[var(--color-sumi)]">
                {toast.message}
              </span>
              {helpEs && toast.es && (
                <span className="text-xs text-[var(--color-sumi-soft)]">
                  {toast.es}
                </span>
              )}
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
