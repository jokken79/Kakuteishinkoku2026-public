/** Primitivos de UI compartidos: tarjeta papel, estados vacios/error, headings. */
import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

/** Tarjeta de papel: superficie blanca, hairline fina, sombra casi nula. */
export function Card({
  children,
  className,
  as: As = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article";
}) {
  return (
    <As
      className={`rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] shadow-[var(--shadow-paper)] ${className ?? ""}`}
    >
      {children}
    </As>
  );
}

/** Estado vacio que guia (CTA), nunca un vacio mudo. */
export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon: IconName;
  title: string;
  hint: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 grid h-16 w-16 place-items-center rounded-full bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
        <Icon name={icon} className="h-7 w-7" />
      </div>
      <p className="text-base font-medium text-[var(--color-sumi)]">{title}</p>
      <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-[var(--color-sumi-soft)]">
        {hint}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/** Estado de error con voz clara (japones), no "Error 500". */
export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 grid h-12 w-12 place-items-center rounded-full bg-[var(--color-kohaku-soft)] text-[var(--color-kohaku)]">
        <Icon name="shield" className="h-6 w-6" />
      </div>
      <p className="max-w-sm text-sm leading-relaxed text-[var(--color-sumi)]">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-4 py-2 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
        >
          再試行
        </button>
      )}
    </div>
  );
}

/** Skeleton de carga sereno (papel que respira). */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-[var(--radius-card)] bg-[var(--color-paper-sink)] ${className ?? ""}`}
    />
  );
}

/** Fallback de pantalla para imports dinamicos. Mantiene el layout estable. */
export function ScreenLoading({
  label = "読み込み中です。",
}: {
  label?: string;
}) {
  return (
    <section
      className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-5 sm:px-6 lg:px-8"
      aria-busy="true"
      aria-live="polite"
    >
      <p className="text-sm font-medium text-[var(--color-sumi)]">{label}</p>
      <Skeleton className="h-28 w-full" />
      <div className="grid gap-3 md:grid-cols-3">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
    </section>
  );
}

/** Etiqueta-titulo de seccion (sentence case, sereno). */
export function Label({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--color-sumi-soft)]">
      {children}
    </span>
  );
}
