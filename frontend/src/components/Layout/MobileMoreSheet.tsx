/**
 * Bottom sheet "もっと" para la nav móvil.
 *
 * Lista todas las secciones que NO entran en la barra principal. Al tocar
 * una sección ready, navega y cierra el sheet. Las secciones 準備中 se
 * muestran deshabilitadas con su badge. Animación Framer Motion serena.
 *
 * Accesibilidad:
 * - role="dialog" + aria-modal + aria-label en el panel.
 * - Foco atrapado en el sheet mientras está abierto (Escape cierra).
 * - Overlay clickeable cierra el sheet.
 */
import { Fragment, useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { NAV_GROUPS, NAV_SECTIONS, MOBILE_PRIMARY_IDS } from "../../lib/navigation";
import { preloadScreen } from "../../lib/screenRegistry";
import { useUiStore } from "../../lib/store";
import { Icon, type IconName } from "../Icon";
import { HelpSubtitle } from "../HelpTerm";
import {
  moreSheetOverlayVariants,
  moreSheetPanelVariants,
  moreSheetListVariants,
  moreSheetItemVariants,
} from "../../variants/moreSheetVariants";

interface MobileMoreSheetProps {
  open: boolean;
  onClose: () => void;
}

/** Secciones que van al sheet (todo lo que NO está en la barra primaria). */
const MORE_SECTIONS = NAV_SECTIONS.filter(
  (s) => !(MOBILE_PRIMARY_IDS as readonly string[]).includes(s.id),
);

export function MobileMoreSheet({ open, onClose }: MobileMoreSheetProps) {
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  const activeSection = useUiStore((s) => s.activeSection);
  const panelRef = useRef<HTMLDivElement>(null);

  // Cerrar con Escape y atrapar foco dentro del sheet.
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      // Trampa de foco: Tab cicla dentro del panel.
      if (e.key === "Tab" && panelRef.current) {
        const focusable = panelRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener("keydown", onKeyDown);

    // Mover foco al panel al abrir.
    const frame = requestAnimationFrame(() => {
      panelRef.current?.focus();
    });

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      cancelAnimationFrame(frame);
    };
  }, [open, onClose]);

  function handleSelect(id: string, ready: boolean) {
    if (!ready) return;
    setActiveSection(id);
    onClose();
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Overlay */}
          <motion.div
            key="more-sheet-overlay"
            variants={moreSheetOverlayVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="fixed inset-0 z-30 bg-[var(--color-sumi)]/20 backdrop-blur-[2px] lg:hidden"
            aria-hidden
            onClick={onClose}
          />

          {/* Panel */}
          <motion.div
            key="more-sheet-panel"
            ref={panelRef}
            role="dialog"
            aria-modal
            aria-label="その他のメニュー"
            tabIndex={-1}
            variants={moreSheetPanelVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="fixed inset-x-0 bottom-0 z-40 rounded-t-[20px] border-t border-[var(--color-hairline)] bg-[var(--color-surface)] pb-[env(safe-area-inset-bottom)] shadow-[var(--shadow-lift)] lg:hidden"
          >
            {/* Asa visual */}
            <div className="flex justify-center pt-3 pb-1" aria-hidden>
              <span className="h-1 w-10 rounded-full bg-[var(--color-hairline)]" />
            </div>

            {/* Encabezado */}
            <div className="flex items-center justify-between px-5 py-3">
              <p className="text-[13px] font-semibold text-[var(--color-sumi)]">
                その他
              </p>
              <button
                type="button"
                onClick={onClose}
                aria-label="メニューを閉じる"
                className="grid h-7 w-7 place-items-center rounded-full text-[var(--color-sumi-soft)] transition-colors hover:bg-[var(--color-paper-sink)] hover:text-[var(--color-sumi)]"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.6}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-4 w-4"
                  aria-hidden
                >
                  <path d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Lista de secciones */}
            <motion.ul
              role="list"
              variants={moreSheetListVariants}
              initial="hidden"
              animate="visible"
              className="grid grid-cols-2 gap-1.5 px-4 pb-5"
            >
              {NAV_GROUPS.map((group) => {
                const sections = MORE_SECTIONS.filter((section) => section.group === group.id);
                if (sections.length === 0) return null;
                return (
                  <Fragment key={group.id}>
                    <li className="col-span-2 px-2 pt-2 text-[10px] font-semibold text-[var(--color-sumi-soft)]">
                      {group.label}
                      <span className="ml-1.5 font-normal">{group.es}</span>
                    </li>
                    {sections.map((section) => {
                      const selected = section.id === activeSection;
                      return (
                        <motion.li key={section.id} variants={moreSheetItemVariants}>
                    <button
                      type="button"
                      disabled={!section.ready}
                      onPointerEnter={() => preloadScreen(section.id)}
                      onFocus={() => preloadScreen(section.id)}
                      onClick={() => handleSelect(section.id, section.ready)}
                      aria-current={selected ? "page" : undefined}
                      className={[
                        "flex w-full items-center gap-3 rounded-[12px] px-3.5 py-3 text-left transition-colors",
                        !section.ready
                          ? "cursor-not-allowed opacity-45"
                          : selected
                            ? "bg-[var(--color-surface)] font-semibold text-[var(--color-sumi)] shadow-[var(--shadow-paper)]"
                            : "text-[var(--color-sumi-soft)] hover:bg-[var(--color-paper-sink)] hover:text-[var(--color-sumi)]",
                      ].join(" ")}
                    >
                      <Icon
                        name={section.icon as IconName}
                        className={`h-5 w-5 shrink-0 ${
                          selected
                            ? "text-[var(--color-seiji)]"
                            : "text-[var(--color-sumi-soft)]"
                        }`}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] leading-snug">
                          {section.label}
                        </span>
                        <HelpSubtitle className="text-[10px]">
                          {section.es}
                        </HelpSubtitle>
                        {!section.ready && (
                          <span className="mt-0.5 block text-[9px] text-[var(--color-sumi-soft)]">
                            準備中
                          </span>
                        )}
                      </span>
                    </button>
                        </motion.li>
                      );
                    })}
                  </Fragment>
                );
              })}
            </motion.ul>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
