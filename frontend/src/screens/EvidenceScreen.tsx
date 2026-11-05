/** Archivo local de 領収書・証明書 con búsqueda por los índices de 電帳法. */
import { useState, type FormEvent, type ReactNode } from "react";
import { motion } from "framer-motion";
import { evidenceFileUrl, type EvidenceFilters, type EvidenceItem } from "../lib/api";
import { useActiveYear, useEvidence } from "../lib/hooks";
import { useUiStore } from "../lib/store";
import { formatYen, toReiwa } from "../lib/format";
import { Card, EmptyState, ErrorState, Skeleton } from "../components/ui";
import { HelpSubtitle, HelpTerm } from "../components/HelpTerm";
import { Icon } from "../components/Icon";
import { screenVariants } from "../variants/layoutVariants";

interface FilterDraft {
  vendor: string;
  dateFrom: string;
  dateTo: string;
  amountMin: string;
  amountMax: string;
}

const EMPTY_FILTERS: FilterDraft = {
  vendor: "",
  dateFrom: "",
  dateTo: "",
  amountMin: "",
  amountMax: "",
};

const STATUS_LABEL: Record<EvidenceItem["status"], string> = {
  pending: "確認待ち",
  confirmed: "確認済み",
  rejected: "対象外",
};

export function EvidenceScreen() {
  const activeYear = useActiveYear();
  const setActiveSection = useUiStore((state) => state.setActiveSection);
  const [draft, setDraft] = useState<FilterDraft>(EMPTY_FILTERS);
  const [filters, setFilters] = useState<EvidenceFilters>({});
  const evidence = useEvidence(filters);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFilters({
      vendor: draft.vendor.trim() || undefined,
      dateFrom: draft.dateFrom || undefined,
      dateTo: draft.dateTo || undefined,
      amountMin: draft.amountMin === "" ? undefined : Number(draft.amountMin),
      amountMax: draft.amountMax === "" ? undefined : Number(draft.amountMax),
    });
  };

  const reset = () => {
    setDraft(EMPTY_FILTERS);
    setFilters({});
  };

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-6xl px-4 py-6 sm:px-8 sm:py-10"
    >
      <header className="mb-6 flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
          <Icon name="archive" className="h-5 w-5" />
        </div>
        <div>
          <h2 className="flex items-center text-xl font-bold text-[var(--color-sumi)]">
            領収書・証明書
            <HelpTerm term="電子帳簿保存法" size="md" />
          </h2>
          <HelpSubtitle>Comprobantes y documentos archivados</HelpSubtitle>
          <p className="text-sm text-[var(--color-sumi-soft)]">
            {toReiwa(activeYear)}分・日付／金額／取引先で検索
          </p>
        </div>
      </header>

      <Card as="section" className="mb-5 p-4 sm:p-5">
        <form onSubmit={submit} className="grid gap-3 lg:grid-cols-[minmax(180px,1.4fr)_repeat(4,minmax(120px,1fr))_auto]">
          <FilterField label="取引先">
            <input
              type="search"
              value={draft.vendor}
              onChange={(event) => setDraft((current) => ({ ...current, vendor: event.target.value }))}
              placeholder="店舗名・会社名"
              className="h-10 w-full rounded-[8px] border border-[var(--color-hairline)] bg-[var(--color-paper)] px-3 text-sm text-[var(--color-sumi)] outline-none focus:border-[var(--color-seiji)]"
            />
          </FilterField>
          <FilterField label="開始日">
            <input
              type="date"
              value={draft.dateFrom}
              onChange={(event) => setDraft((current) => ({ ...current, dateFrom: event.target.value }))}
              className="h-10 w-full rounded-[8px] border border-[var(--color-hairline)] bg-[var(--color-paper)] px-2 text-sm text-[var(--color-sumi)] outline-none focus:border-[var(--color-seiji)]"
            />
          </FilterField>
          <FilterField label="終了日">
            <input
              type="date"
              value={draft.dateTo}
              onChange={(event) => setDraft((current) => ({ ...current, dateTo: event.target.value }))}
              className="h-10 w-full rounded-[8px] border border-[var(--color-hairline)] bg-[var(--color-paper)] px-2 text-sm text-[var(--color-sumi)] outline-none focus:border-[var(--color-seiji)]"
            />
          </FilterField>
          <FilterField label="最低金額">
            <input
              type="number"
              min={0}
              inputMode="numeric"
              value={draft.amountMin}
              onChange={(event) => setDraft((current) => ({ ...current, amountMin: event.target.value }))}
              placeholder="0"
              className="h-10 w-full rounded-[8px] border border-[var(--color-hairline)] bg-[var(--color-paper)] px-3 text-right text-sm tabular text-[var(--color-sumi)] outline-none focus:border-[var(--color-seiji)]"
            />
          </FilterField>
          <FilterField label="最高金額">
            <input
              type="number"
              min={0}
              inputMode="numeric"
              value={draft.amountMax}
              onChange={(event) => setDraft((current) => ({ ...current, amountMax: event.target.value }))}
              placeholder="上限なし"
              className="h-10 w-full rounded-[8px] border border-[var(--color-hairline)] bg-[var(--color-paper)] px-3 text-right text-sm tabular text-[var(--color-sumi)] outline-none focus:border-[var(--color-seiji)]"
            />
          </FilterField>
          <div className="flex items-end gap-2">
            <button
              type="submit"
              className="h-10 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-4 text-sm font-semibold text-white"
            >
              検索
            </button>
            <button
              type="button"
              onClick={reset}
              className="h-10 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3 text-sm text-[var(--color-sumi)]"
            >
              解除
            </button>
          </div>
        </form>
      </Card>

      {evidence.isLoading && <Skeleton className="h-64" />}
      {evidence.isError && (
        <Card>
          <ErrorState
            message={evidence.error instanceof Error ? evidence.error.message : "保存書類を読み込めませんでした。"}
            onRetry={() => void evidence.refetch()}
          />
        </Card>
      )}

      {evidence.data && (
        <>
          <div className="mb-3 flex items-end justify-between gap-4">
            <div>
              <p className="text-lg font-semibold text-[var(--color-sumi)]">
                {evidence.data.total_count}件
              </p>
              <HelpSubtitle>{`Total archivado: ${formatYen(evidence.data.total_amount)}`}</HelpSubtitle>
            </div>
            <button
              type="button"
              onClick={() => setActiveSection("capture")}
              className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3 py-1.5 text-xs font-medium text-[var(--color-sumi)]"
            >
              <Icon name="camera" className="h-3.5 w-3.5" />
              書類を追加
            </button>
          </div>

          {evidence.data.items.length === 0 ? (
            <Card>
              <EmptyState
                icon="archive"
                title="条件に一致する書類はありません"
                hint="検索条件を解除するか、領収書を撮影して追加してください。"
                action={
                  <button
                    type="button"
                    onClick={() => setActiveSection("capture")}
                    className="rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-4 py-2 text-sm font-medium text-white"
                  >
                    領収書を撮影
                  </button>
                }
              />
            </Card>
          ) : (
            <EvidenceResults items={evidence.data.items} />
          )}
        </>
      )}
    </motion.div>
  );
}

function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid min-w-0 gap-1">
      <span className="text-[11px] font-medium text-[var(--color-sumi-soft)]">{label}</span>
      {children}
    </label>
  );
}

function EvidenceResults({ items }: { items: EvidenceItem[] }) {
  return (
    <>
      <Card className="hidden overflow-hidden md:block">
        <table className="w-full table-fixed border-collapse text-left">
          <thead className="bg-[var(--color-paper-sink)] text-[11px] text-[var(--color-sumi-soft)]">
            <tr>
              <th className="w-32 px-4 py-3 font-medium">日付</th>
              <th className="px-4 py-3 font-medium">取引先</th>
              <th className="w-36 px-4 py-3 text-right font-medium">金額</th>
              <th className="w-28 px-4 py-3 font-medium">状態</th>
              <th className="w-28 px-4 py-3 text-right font-medium">原本</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-hairline)]">
            {items.map((item) => (
              <tr key={item.id} className="text-sm text-[var(--color-sumi)]">
                <td className="px-4 py-3 tabular">{item.date ?? "日付不明"}</td>
                <td className="truncate px-4 py-3 font-medium">{item.vendor ?? "取引先不明"}</td>
                <td className="px-4 py-3 text-right tabular">{formatYen(item.amount ?? 0)}</td>
                <td className="px-4 py-3 text-xs">{STATUS_LABEL[item.status]}</td>
                <td className="px-4 py-3 text-right">
                  <EvidenceFileLink item={item} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div className="space-y-2 md:hidden">
        {items.map((item) => (
          <article
            key={item.id}
            className="rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-[var(--color-sumi)]">
                  {item.vendor ?? "取引先不明"}
                </p>
                <p className="mt-1 text-xs tabular text-[var(--color-sumi-soft)]">
                  {item.date ?? "日付不明"}・{STATUS_LABEL[item.status]}
                </p>
              </div>
              <p className="shrink-0 text-sm font-semibold tabular text-[var(--color-sumi)]">
                {formatYen(item.amount ?? 0)}
              </p>
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-[var(--color-hairline)] pt-3">
              <span className="text-[11px] text-[var(--color-sumi-soft)]">
                保存期限 {item.retention_until ?? "未設定"}
              </span>
              <EvidenceFileLink item={item} />
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

function EvidenceFileLink({ item }: { item: EvidenceItem }) {
  if (!item.file_available) {
    return (
      <span className="whitespace-nowrap text-[11px] text-[var(--color-sumi-soft)]">
        ファイルなし
      </span>
    );
  }
  return (
    <a
      href={evidenceFileUrl(item.id)}
      className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--color-seiji)] hover:underline"
    >
      <Icon name="file" className="h-3.5 w-3.5" />
      保存
    </a>
  );
}
