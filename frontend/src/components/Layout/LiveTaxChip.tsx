/**
 * Chip del impuesto estimado en vivo (header). Muestra el 還付金/納付額 que sale
 * del MISMO motor que la pantalla 確定申告 (`/filing/draft`), de modo que el
 * numero es CONSISTENTE en toda la app (header, dashboard y filing coinciden).
 * Sereno; el signo lo marca el color (celadon = 還付, sumi = 納付).
 */
import { useFilingDraft } from "../../lib/hooks";
import { formatYen } from "../../lib/format";

export function LiveTaxChip() {
  const { data: filing, isLoading, isError } = useFilingDraft();

  if (isError) {
    return <span className="hidden text-xs text-[var(--color-sumi-soft)] sm:inline">税額未取得</span>;
  }

  if (isLoading || !filing) {
    return (
      <div className="hidden h-8 w-28 animate-pulse rounded-[var(--radius-pill)] bg-[var(--color-paper-sink)] sm:block" />
    );
  }

  const isRefund = filing.is_refund;
  const label = isRefund ? "還付見込" : "納付見込";

  return (
    <div className="flex items-center gap-2 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-2 py-1.5 sm:px-3">
      <span className="hidden text-[10px] font-medium text-[var(--color-sumi-soft)] sm:inline">
        {label}
      </span>
      <span
        className={`whitespace-nowrap tabular text-xs font-semibold sm:text-sm ${isRefund ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]"}`}
      >
        {formatYen(Math.abs(filing.final_amount))}
      </span>
    </div>
  );
}
