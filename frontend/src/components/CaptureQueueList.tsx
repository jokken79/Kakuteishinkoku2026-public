/**
 * Tira de capturas del 連続撮影: una tarjeta por foto tomada, con su estado de
 * subida y — cuando el OCR ya respondio — el 仕訳 propuesto con 科目 elegible y
 * confirmacion de UN toque, sin salir de la pantalla de la camara.
 */
import { AnimatePresence, motion } from "framer-motion";
import type { CaptureItem, CaptureStatus } from "../lib/captureQueue";
import { EXPENSE_CATEGORIES, categoryForAccount } from "../lib/expenseCategories";
import { formatDate, formatYen } from "../lib/format";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Icon } from "./Icon";
import { Card } from "./ui";

interface CaptureQueueListProps {
  items: readonly CaptureItem[];
  /** Confirma el 仕訳 de una captura con el 科目 elegido (1 toque). */
  onConfirm: (item: CaptureItem, accountCode: string) => void;
  /** Cambia el 科目 propuesto antes de confirmar. */
  onAccountChange: (item: CaptureItem, accountCode: string) => void;
  /** Reintenta una captura que fallo. */
  onRetry: (id: string) => void;
  /** Descarta una captura de la tira. */
  onDismiss: (id: string) => void;
  /** Ids con una confirmacion en vuelo (para deshabilitar el boton). */
  confirming: ReadonlySet<string>;
  disabled?: boolean;
}

const STATUS_LABEL: Record<CaptureStatus, string> = {
  queued: "順番待ち",
  uploading: "読み取り中",
  done: "確認待ち",
  duplicate: "重複の可能性",
  offline: "オフライン保存",
  error: "失敗",
};

const STATUS_TONE: Record<CaptureStatus, { bg: string; fg: string }> = {
  queued: { bg: "var(--color-paper-sink)", fg: "var(--color-sumi-soft)" },
  uploading: { bg: "#dbeafe", fg: "#1d4ed8" },
  done: { bg: "var(--color-seiji-soft)", fg: "var(--color-seiji)" },
  duplicate: { bg: "var(--color-kohaku-soft)", fg: "var(--color-kohaku)" },
  offline: { bg: "var(--color-kohaku-soft)", fg: "var(--color-kohaku)" },
  error: { bg: "var(--color-kohaku-soft)", fg: "var(--color-kohaku)" },
};

export function CaptureQueueList({
  items,
  onConfirm,
  onAccountChange,
  onRetry,
  onDismiss,
  confirming,
  disabled = false,
}: CaptureQueueListProps) {
  if (items.length === 0) return null;

  return (
    <ul className="mt-4 space-y-3">
      <AnimatePresence initial={false}>
        {items.map((item) => (
          <motion.li
            key={item.id}
            layout
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          >
            <CaptureRow
              item={item}
              onConfirm={onConfirm}
              onAccountChange={onAccountChange}
              onRetry={onRetry}
              onDismiss={onDismiss}
              confirming={confirming.has(item.id)}
              disabled={disabled}
            />
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}

interface CaptureRowProps {
  item: CaptureItem;
  onConfirm: (item: CaptureItem, accountCode: string) => void;
  onAccountChange: (item: CaptureItem, accountCode: string) => void;
  onRetry: (id: string) => void;
  onDismiss: (id: string) => void;
  confirming: boolean;
  disabled: boolean;
}

function CaptureRow({
  item,
  onConfirm,
  onAccountChange,
  onRetry,
  onDismiss,
  confirming,
  disabled,
}: CaptureRowProps) {
  const tone = STATUS_TONE[item.status];
  const result = item.result;
  const accountCode =
    result?.journal_suggestion.account_code ?? result?.transaction.account_code ?? null;
  const category = categoryForAccount(accountCode);
  const busy = item.status === "queued" || item.status === "uploading";

  return (
    <Card className="p-3.5">
      <div className="flex items-start gap-3">
        {item.thumbUrl ? (
          <img
            src={item.thumbUrl}
            alt=""
            className="h-16 w-12 shrink-0 rounded-[8px] border border-[var(--color-hairline)] object-cover"
          />
        ) : (
          <div className="grid h-16 w-12 shrink-0 place-items-center rounded-[8px] bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
            <Icon name="receipt" className="h-5 w-5" />
          </div>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span
              className="rounded-[var(--radius-pill)] px-2 py-0.5 text-[11px] font-semibold"
              style={{ backgroundColor: tone.bg, color: tone.fg }}
            >
              {STATUS_LABEL[item.status]}
            </span>
            {result && <ConfidenceBadge score={result.confidence} />}
          </div>

          {busy && (
            <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-[var(--color-paper-sink)]">
              <motion.div
                className="h-full w-1/3 rounded-full bg-[var(--color-seiji)]"
                animate={{ x: ["-100%", "300%"] }}
                transition={{ duration: 1.1, repeat: Infinity, ease: "easeInOut" }}
              />
            </div>
          )}

          {result && (
            <div className="mt-2 space-y-0.5">
              <p className="truncate text-sm font-medium text-[var(--color-sumi)]">
                {result.transaction.vendor ?? "取引先不明"}
              </p>
              <p className="tabular text-sm text-[var(--color-sumi-soft)]">
                {formatDate(result.transaction.date)}・
                {formatYen(result.transaction.total_amount)}
              </p>
            </div>
          )}

          {item.error && !result && (
            <p className="mt-2 text-xs text-[var(--color-sumi-soft)]">{item.error}</p>
          )}
          {item.warning && (
            <p className="mt-2 text-xs text-[var(--color-kohaku)]">{item.warning}</p>
          )}

          {item.status === "duplicate" && (
            <p className="mt-2 text-xs text-[var(--color-kohaku)]">
              同じ写真がすでに登録済みです。二重計上を防ぐため、既存の取引を表示しています。
            </p>
          )}
          {item.status === "done" && result?.duplicate_of && (
            <p className="mt-2 text-xs text-[var(--color-kohaku)]">
              同じ日付・金額の取引がすでにあります。二重計上でないか確認してください。
            </p>
          )}
          {result?.account_source === "learned" && (
            <p className="mt-2 text-xs text-[var(--color-seiji)]">
              前回この取引先で選んだ科目を使いました。
            </p>
          )}
        </div>
      </div>

      {result && !item.confirmed && (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {EXPENSE_CATEGORIES.map((cat) => {
              const active = cat.accountCode === category.accountCode;
              return (
                <button
                  key={cat.id}
                  type="button"
                  disabled={disabled || confirming}
                  onClick={() => onAccountChange(item, cat.accountCode)}
                  className={`rounded-[var(--radius-pill)] px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
                    active
                      ? "bg-[var(--color-seiji)] text-white"
                      : "bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)] hover:bg-[var(--color-hairline)]"
                  }`}
                  aria-pressed={active}
                >
                  <span aria-hidden="true">{cat.emoji}</span> {cat.labelJa}
                </button>
              );
            })}
          </div>
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              disabled={disabled || confirming}
              onClick={() => onConfirm(item, category.accountCode)}
              className="flex flex-1 items-center justify-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-shuiro)] py-2.5 text-sm font-semibold text-white transition-transform active:translate-y-px disabled:opacity-50"
            >
              <Icon name="check" className="h-4 w-4" />
              {confirming ? "登録中…" : "この内容で確定"}
            </button>
            <button
              type="button"
              onClick={() => onDismiss(item.id)}
              className="rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3 py-2 text-xs font-medium text-[var(--color-sumi-soft)] transition-colors hover:bg-[var(--color-paper-sink)]"
            >
              あとで
            </button>
          </div>
        </>
      )}

      {item.confirmed && (
        <p className="mt-3 flex items-center gap-1.5 text-sm font-medium text-[var(--color-seiji)]">
          <Icon name="check" className="h-4 w-4" />
          登録しました
        </p>
      )}

      {(item.status === "error" || item.status === "offline") && (
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            onClick={() => onRetry(item.id)}
            disabled={disabled}
            className="flex-1 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] py-2 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)] disabled:opacity-50"
          >
            もう一度送信
          </button>
          <button
            type="button"
            onClick={() => onDismiss(item.id)}
            className="rounded-[var(--radius-pill)] px-3 py-2 text-xs font-medium text-[var(--color-sumi-soft)] transition-colors hover:bg-[var(--color-paper-sink)]"
          >
            削除
          </button>
        </div>
      )}
    </Card>
  );
}
