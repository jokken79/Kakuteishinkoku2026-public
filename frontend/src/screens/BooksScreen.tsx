/** 帳簿: estado contable y descarga directa de 仕訳帳・総勘定元帳. */
import { motion } from "framer-motion";
import { filingPdfUrl } from "../lib/api";
import { useFilingDraft } from "../lib/hooks";
import { useUiStore } from "../lib/store";
import { formatYen } from "../lib/format";
import { Card, ErrorState, Skeleton } from "../components/ui";
import { HelpSubtitle, HelpTerm } from "../components/HelpTerm";
import { Icon, type IconName } from "../components/Icon";
import { screenVariants } from "../variants/layoutVariants";

const BOOKS: readonly {
  form: "shiwakecho" | "motocho";
  title: string;
  help: string;
  icon: IconName;
}[] = [
  {
    form: "shiwakecho",
    title: "仕訳帳",
    help: "Todas las operaciones, ordenadas por fecha.",
    icon: "calendar",
  },
  {
    form: "motocho",
    title: "総勘定元帳",
    help: "Movimientos y saldo acumulado por cuenta contable.",
    icon: "book",
  },
];

export function BooksScreen() {
  const setActiveSection = useUiStore((state) => state.setActiveSection);
  const filing = useFilingDraft();
  const draft = filing.data;

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-4xl px-4 py-6 sm:px-8 sm:py-10"
    >
      <header className="mb-6 flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
          <Icon name="book" className="h-5 w-5" />
        </div>
        <div>
          <h2 className="flex items-center text-xl font-bold text-[var(--color-sumi)]">
            帳簿
            <HelpTerm term="帳簿" size="md" />
          </h2>
          <HelpSubtitle>Libros contables</HelpSubtitle>
          <p className="text-sm text-[var(--color-sumi-soft)]">
            確認済みの仕訳から自動作成
          </p>
        </div>
      </header>

      {filing.isLoading && (
        <div className="space-y-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-52" />
        </div>
      )}

      {filing.isError && (
        <Card>
          <ErrorState
            message={filing.error instanceof Error ? filing.error.message : "帳簿を作成できませんでした。"}
            onRetry={() => void filing.refetch()}
          />
        </Card>
      )}

      {draft && (
        <div className="space-y-5">
          <section className="grid overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] sm:grid-cols-3">
            <BookStat label="確認済み仕訳" value={`${draft.confirmed_count}件`} />
            <BookStat label="経費合計" value={formatYen(draft.confirmed_expense_total)} />
            <BookStat
              label="貸借チェック"
              value={draft.bs_balanced ? "一致" : "要確認"}
              accent={draft.bs_balanced}
            />
          </section>

          {draft.pending_count > 0 && (
            <div className="flex items-start justify-between gap-4 border-l-2 border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-[var(--color-sumi)]">
                  未確認の仕訳が{draft.pending_count}件あります
                </p>
                <HelpSubtitle className="text-[var(--color-sumi)]">
                  Revisa esos asientos antes de guardar los libros definitivos.
                </HelpSubtitle>
              </div>
              <button
                type="button"
                onClick={() => setActiveSection("journal-tray")}
                className="shrink-0 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-1.5 text-xs font-medium text-[var(--color-sumi)]"
              >
                トレイへ
              </button>
            </div>
          )}

          <Card as="section" className="overflow-hidden">
            <div className="border-b border-[var(--color-hairline)] px-5 py-4">
              <h3 className="text-sm font-semibold text-[var(--color-sumi)]">帳簿を出力</h3>
              <HelpSubtitle>Descargar libros en PDF</HelpSubtitle>
            </div>
            <div className="divide-y divide-[var(--color-hairline)]">
              {BOOKS.map((book) => (
                <a
                  key={book.form}
                  href={filingPdfUrl(draft.draft_id, book.form)}
                  target="_blank"
                  rel="noreferrer"
                  className="flex min-h-20 items-center gap-4 px-5 py-4 transition-colors hover:bg-[var(--color-paper-sink)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--color-seiji)]"
                >
                  <Icon name={book.icon} className="h-5 w-5 shrink-0 text-[var(--color-seiji)]" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold text-[var(--color-sumi)]">
                      {book.title}
                    </span>
                    <span className="block text-xs leading-relaxed text-[var(--color-sumi-soft)]">
                      {book.help}
                    </span>
                  </span>
                  <span className="text-[11px] font-semibold text-[var(--color-sumi-soft)]">PDF</span>
                  <Icon name="arrow" className="h-4 w-4 shrink-0 text-[var(--color-sumi-soft)]" />
                </a>
              ))}
            </div>
          </Card>

          <p className="text-xs leading-relaxed text-[var(--color-sumi-soft)]">
            帳簿は現在の確認済み仕訳から毎回再生成されます。仕訳を修正した場合は、もう一度ダウンロードしてください。
          </p>
        </div>
      )}
    </motion.div>
  );
}

function BookStat({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="border-b border-[var(--color-hairline)] px-4 py-4 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0">
      <p className="text-xs text-[var(--color-sumi-soft)]">{label}</p>
      <p className={`mt-1 text-lg font-semibold tabular ${accent ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]"}`}>
        {value}
      </p>
    </div>
  );
}
