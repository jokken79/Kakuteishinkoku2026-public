/** Badge de confianza del OCR: celadon (alta) / ambar (revisar). */
import { confidenceLevel, confidencePct } from "../lib/format";

interface ConfidenceBadgeProps {
  score: number | null | undefined;
  /** Variante compacta (solo punto + %) para listas densas. */
  compact?: boolean;
}

export function ConfidenceBadge({ score, compact = false }: ConfidenceBadgeProps) {
  // Sin score (origen CSV/banco): el dato es exacto, no hay OCR que medir.
  // Mostramos un badge neutro en vez de un "0%" que parece lectura fallida.
  if (score === null || score === undefined) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] bg-[var(--color-paper-sink)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-sumi-soft)]"
        title="銀行・カード明細から取込"
      >
        <span
          className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-sumi-soft)]"
          aria-hidden
        />
        {compact ? "CSV" : "CSV取込"}
      </span>
    );
  }

  const level = confidenceLevel(score);
  const pct = confidencePct(score);
  const high = level === "high";

  const label = high ? "高信頼" : "要確認";
  const tone = high
    ? "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]"
    : "bg-[var(--color-kohaku-soft)] text-[var(--color-kohaku)]";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] px-2.5 py-1 text-[11px] font-medium ${tone}`}
      title={`OCR信頼度 ${pct}%`}
    >
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${high ? "bg-[var(--color-seiji)]" : "bg-[var(--color-kohaku)]"}`}
        aria-hidden
      />
      {compact ? (
        <span className="tabular">{pct}%</span>
      ) : (
        <>
          <span>{label}</span>
          <span className="tabular opacity-70">{pct}%</span>
        </>
      )}
    </span>
  );
}
