/**
 * Capa de ayuda en castellano sobre la UI japonesa de 確定申告.
 *
 * La interfaz permanece SIEMPRE en japones (es un documento oficial para
 * Hacienda japonesa). Cuando la ayuda ES esta activa (`helpEs` en el store),
 * estos componentes agregan glosas/subtitulos discretos en castellano para
 * que el owner hispanohablante entienda los terminos fiscales:
 *
 * - `HelpTerm`    : un (?) junto a un termino japones; abre un popover con la
 *                   glosa ES. Accesible por teclado y aria.
 * - `HelpSubtitle`: subtitulo ES pequeno bajo un termino (sin interaccion).
 * - `HelpToggle`  : el control global "ヘルプ: 日本語 ⇄ Español".
 *
 * Diseno "Calma fiscal": la ayuda usa sumi-soft/tonos discretos, NUNCA shuiro
 * (reservado al sello/confirmacion), y no compite con el japones primario.
 */
import { useEffect, useId, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useUiStore } from "../lib/store";
import { lookupTerm } from "../lib/glossary";
import { helpPopoverVariants } from "../variants/helpVariants";

// --- (?) contextual con popover -------------------------------------------

interface HelpTermProps {
  /**
   * Termino japones a explicar. Si se omite, se usa `children` como termino.
   * Se resuelve contra el glosario con `lookupTerm` (tolera sufijos/variantes).
   */
  term?: string;
  /** Glosa ES explicita (override del glosario, p.ej. para frases compuestas). */
  help?: string;
  /** Etiqueta ES corta opcional para el encabezado del popover. */
  esLabel?: string;
  /** Tamano del icono. */
  size?: "sm" | "md";
}

/**
 * Boton (?) que, con la ayuda ES activa, abre un popover con la explicacion en
 * castellano del termino fiscal japones. Si la ayuda esta desactivada o el
 * termino no esta en el glosario (sin `help` explicito), no renderiza nada.
 */
export function HelpTerm({ term, help, esLabel, size = "sm" }: HelpTermProps) {
  const helpEs = useUiStore((s) => s.helpEs);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const popId = useId();

  // Cierre por click-fuera y Escape (popover accesible).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!helpEs) return null;

  const entry = term ? lookupTerm(term) : undefined;
  const glossES = help ?? entry?.help;
  if (!glossES) return null;

  const label = esLabel ?? entry?.es ?? "Ayuda";
  const dim = size === "md" ? "h-4 w-4 text-[10px]" : "h-3.5 w-3.5 text-[9px]";

  return (
    <span ref={wrapRef} className="relative inline-flex align-middle">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={open ? popId : undefined}
        aria-label={`${term ?? label}（スペイン語の説明）`}
        className={`ml-1 inline-grid ${dim} place-items-center rounded-full border border-[var(--color-hairline)] font-semibold leading-none text-[var(--color-sumi-soft)] transition-colors hover:border-[var(--color-seiji)] hover:text-[var(--color-seiji)]`}
      >
        ?
      </button>

      <AnimatePresence>
        {open && (
          <motion.span
            id={popId}
            role="tooltip"
            variants={helpPopoverVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="absolute left-0 top-full z-30 mt-1.5 block w-64 rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] p-3 text-left shadow-[var(--shadow-lift)]"
          >
            <span className="mb-1 flex items-center gap-1.5">
              <span className="inline-flex items-center rounded-[var(--radius-pill)] bg-[var(--color-paper-sink)] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-sumi-soft)]">
                ES
              </span>
              <span className="text-xs font-semibold text-[var(--color-sumi)]">
                {label}
              </span>
            </span>
            <span className="block text-xs leading-relaxed text-[var(--color-sumi-soft)]">
              {glossES}
            </span>
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}

// --- Subtitulo ES discreto -------------------------------------------------

interface HelpSubtitleProps {
  /** Termino japones (se busca su etiqueta ES en el glosario). */
  term?: string;
  /** Texto ES explicito (override del glosario). */
  children?: string;
  /** Clases extra (p.ej. para alinear o ajustar el tamano). */
  className?: string;
}

/**
 * Subtitulo en castellano pequeno y discreto (sumi-soft). Solo visible con la
 * ayuda ES activa. Util bajo titulos de pantalla o labels donde un (?) seria
 * demasiado interactivo.
 */
export function HelpSubtitle({ term, children, className }: HelpSubtitleProps) {
  const helpEs = useUiStore((s) => s.helpEs);
  if (!helpEs) return null;

  const text = children ?? (term ? lookupTerm(term)?.es : undefined);
  if (!text) return null;

  return (
    <span
      className={`block text-[11px] font-normal leading-snug text-[var(--color-sumi-soft)] ${className ?? ""}`}
    >
      {text}
    </span>
  );
}

// --- Toggle global de la ayuda ES ------------------------------------------

interface HelpToggleProps {
  /** Variante visual: `compact` para el header, `full` para Settings. */
  variant?: "compact" | "full";
}

/**
 * Control que activa/desactiva la capa de ayuda en castellano. Persiste la
 * preferencia en el store (localStorage). En `compact` (header) muestra un
 * boton "ES" con estado; en `full` (Settings) una fila descriptiva con switch.
 */
export function HelpToggle({ variant = "compact" }: HelpToggleProps) {
  const helpEs = useUiStore((s) => s.helpEs);
  const toggleHelpEs = useUiStore((s) => s.toggleHelpEs);

  if (variant === "compact") {
    return (
      <button
        type="button"
        role="switch"
        aria-checked={helpEs}
        onClick={toggleHelpEs}
        title={
          helpEs
            ? "スペイン語ヘルプ：オン（クリックで日本語のみ）"
            : "スペイン語ヘルプ：オフ（クリックで Español の説明を表示）"
        }
        aria-label="スペイン語ヘルプの切り替え"
        className={`inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
          helpEs
            ? "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]"
            : "border-[var(--color-hairline)] text-[var(--color-sumi-soft)] hover:bg-[var(--color-paper-sink)]"
        }`}
      >
        <span
          className={`h-1.5 w-1.5 rounded-full ${helpEs ? "bg-[var(--color-seiji)]" : "bg-[var(--color-sumi-soft)]"}`}
          aria-hidden
        />
        ES
      </button>
    );
  }

  // variant === "full" (Settings)
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]">
          <span className="text-[13px] font-bold">ES</span>
        </div>
        <div>
          <p className="text-sm font-semibold text-[var(--color-sumi)]">
            スペイン語ヘルプ
            <span className="ml-2 text-xs font-normal text-[var(--color-sumi-soft)]">
              ヘルプ: 日本語 ⇄ Español
            </span>
          </p>
          <p className="mt-1 max-w-md text-xs leading-relaxed text-[var(--color-sumi-soft)]">
            画面は日本語のままで、税務用語にスペイン語の説明（?）と小さな字幕を表示します。公式の申告内容は日本語です。
            <span className="mt-1 block text-[var(--color-sumi-soft)]">
              La interfaz sigue en japones; esto solo agrega explicaciones en
              castellano de los terminos fiscales.
            </span>
          </p>
        </div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={helpEs}
        aria-label="スペイン語ヘルプを有効化"
        onClick={toggleHelpEs}
        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors ${helpEs ? "bg-[var(--color-seiji)]" : "bg-[var(--color-hairline)]"}`}
      >
        <motion.span
          layout
          className="inline-block h-5 w-5 rounded-full bg-white shadow-[var(--shadow-paper)]"
          animate={{ x: helpEs ? 22 : 2 }}
          transition={{ type: "spring", stiffness: 500, damping: 32 }}
        />
      </button>
    </div>
  );
}
