/**
 * 取り込み (CSV import). Sube el extracto del banco/tarjeta -> preview de las
 * filas detectadas (fecha / 取引先 / 金額 / 勘定科目 editable / 重複) -> selecciona
 * y confirma -> los 仕訳 entran a la bandeja. Mobile-first, voz de la interfaz.
 *
 * No reemplaza al OCR: es la segunda via para registrar gastos sin fotografiar
 * cada recibo. Igual que OCR, nada se auto-confirma: todo nace pending.
 */
import { useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useActiveYearLock, useImportCommit, useImportPreview } from "../lib/hooks";
import {
  ApiError,
  type CsvCommitRow,
  type CsvPreviewResponse,
  type CsvPreviewRow,
} from "../lib/api";
import { useUiStore } from "../lib/store";
import { EXPENSE_ACCOUNTS, formatDate, formatYen } from "../lib/format";
import { Card, EmptyState, Label } from "../components/ui";
import { Icon } from "../components/Icon";
import { screenVariants } from "../variants/layoutVariants";

/** Edicion local del 勘定科目 por fila (hash -> code), sobre el preview. */
type AccountEdits = Record<string, string>;

export function ImportScreen() {
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  const { isReadOnly, label: lockLabel } = useActiveYearLock();
  const preview = useImportPreview();
  const commit = useImportCommit();
  const fileInput = useRef<HTMLInputElement>(null);

  const [dragging, setDragging] = useState(false);
  const [data, setData] = useState<CsvPreviewResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [accountEdits, setAccountEdits] = useState<AccountEdits>({});
  const [error, setError] = useState<string | null>(null);
  const [committed, setCommitted] = useState<{
    imported: number;
    skipped: number;
  } | null>(null);

  // Filas que el usuario puede importar (gastos validos, no duplicados).
  const importableRows = useMemo(
    () => (data?.rows ?? []).filter((r) => r.importable),
    [data],
  );

  const resetTo = (next: CsvPreviewResponse | null) => {
    setData(next);
    setCommitted(null);
    setError(null);
    // Por defecto, todas las importables quedan seleccionadas.
    const ids = new Set((next?.rows ?? []).filter((r) => r.importable).map((r) => r.dedup_hash));
    setSelected(ids);
    setAccountEdits({});
  };

  const handleFile = (file: File | undefined) => {
    if (!file || isReadOnly) return;
    setError(null);
    setCommitted(null);
    preview.mutate(
      { file },
      {
        onSuccess: (res) => resetTo(res),
        onError: (err) =>
          setError(
            err instanceof ApiError
              ? err.message
              : "CSVの読み取りに失敗しました。ファイル形式をご確認ください。",
          ),
      },
    );
  };

  const toggle = (hash: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(hash)) next.delete(hash);
      else next.add(hash);
      return next;
    });

  const allSelected =
    importableRows.length > 0 && importableRows.every((r) => selected.has(r.dedup_hash));
  const toggleAll = () =>
    setSelected(
      allSelected ? new Set() : new Set(importableRows.map((r) => r.dedup_hash)),
    );

  const setAccount = (hash: string, code: string) =>
    setAccountEdits((prev) => ({ ...prev, [hash]: code }));

  const accountOf = (row: CsvPreviewRow) =>
    accountEdits[row.dedup_hash] ?? row.account_code ?? "599";

  const selectedTotal = importableRows
    .filter((r) => selected.has(r.dedup_hash))
    .reduce((sum, r) => sum + (r.total_amount ?? 0), 0);

  const handleCommit = () => {
    const rows: CsvCommitRow[] = importableRows
      .filter((r) => selected.has(r.dedup_hash) && r.date && r.total_amount != null)
      .map((r) => ({
        dedup_hash: r.dedup_hash,
        date: r.date as string,
        vendor: r.vendor,
        total_amount: r.total_amount as number,
        account_code: accountOf(r),
        tax_lines: r.tax_lines,
      }));
    if (rows.length === 0 || isReadOnly) return;
    commit.mutate(rows, {
      onSuccess: (res) => {
        setCommitted({ imported: res.imported, skipped: res.skipped_duplicates });
        setData(null);
        setSelected(new Set());
      },
      onError: (err) =>
        setError(
          err instanceof ApiError ? err.message : "取り込みに失敗しました。",
        ),
    });
  };

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-3xl px-4 py-6 sm:px-8 sm:py-10"
    >
      <div className="mb-6">
        <h2 className="text-xl font-bold text-[var(--color-sumi)]">CSVで取り込む</h2>
        <p className="mt-1 text-sm text-[var(--color-sumi-soft)]">
          銀行・カードの明細CSVから、経費の仕訳をまとめて作成します。一枚ずつ撮影する必要はありません。
        </p>
      </div>

      <input
        ref={fileInput}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />

      {/* Resultado del commit */}
      {committed && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <Card className="mb-5 border-[var(--color-seiji)] bg-[var(--color-seiji-soft)] p-5">
            <div className="flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[var(--color-seiji)] text-white">
                <Icon name="check" className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-[var(--color-sumi)]">
                  {committed.imported}件を仕訳トレイに追加しました
                </p>
                {committed.skipped > 0 && (
                  <p className="mt-0.5 text-xs text-[var(--color-sumi-soft)]">
                    {committed.skipped}件は既に登録済みのため除外しました（重複防止）。
                  </p>
                )}
                <button
                  type="button"
                  onClick={() => setActiveSection("journal-tray")}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
                >
                  仕訳トレイで確認
                  <Icon name="arrow" className="h-4 w-4" />
                </button>
              </div>
            </div>
          </Card>
        </motion.div>
      )}

      {/* Zona de subida (cuando no hay preview ni resultado) */}
      {!data && (
        <Card
          as="section"
          className={`relative overflow-hidden border-2 border-dashed p-8 text-center transition-colors ${dragging ? "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)]" : "border-[var(--color-hairline)]"}`}
        >
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              handleFile(e.dataTransfer.files?.[0]);
            }}
            className="flex flex-col items-center"
          >
            {preview.isPending ? (
              <div className="flex flex-col items-center py-6">
                <motion.div
                  className="h-12 w-12 rounded-full border-2 border-[var(--color-hairline)] border-t-[var(--color-seiji)]"
                  animate={{ rotate: 360 }}
                  transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
                />
                <p className="mt-4 text-sm text-[var(--color-sumi-soft)]">
                  CSVを解析中…
                </p>
              </div>
            ) : (
              <>
                {isReadOnly && (
                  <p className="mb-3 rounded-[var(--radius-card)] border border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] px-4 py-3 text-sm font-medium text-[var(--color-sumi)]">
                    {lockLabel}の年度は読み取り専用です。CSV取り込みはできません。
                  </p>
                )}
                <div className="mb-4 grid h-16 w-16 place-items-center rounded-full bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
                  <Icon name="archive" className="h-7 w-7" />
                </div>
                <p className="text-base font-medium text-[var(--color-sumi)]">
                  明細CSVをアップロード
                </p>
                <p className="mt-1.5 max-w-md text-sm text-[var(--color-sumi-soft)]">
                  ここにCSVをドラッグするか、下のボタンから選んでください。UTF-8・SHIFT-JISに対応しています。
                </p>
                <button
                  type="button"
                  onClick={() => fileInput.current?.click()}
                  disabled={isReadOnly}
                  className="mt-5 flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
                >
                  <Icon name="upload" className="h-4 w-4" />
                  CSVファイルを選択
                </button>
              </>
            )}
          </div>
        </Card>
      )}

      {/* Error */}
      {error && (
        <Card className="mt-4 border-[var(--color-kohaku)] p-4">
          <div className="flex items-start gap-3">
            <Icon
              name="shield"
              className="mt-0.5 h-5 w-5 shrink-0 text-[var(--color-kohaku)]"
            />
            <p className="text-sm text-[var(--color-sumi)]">{error}</p>
          </div>
        </Card>
      )}

      {/* Aviso: deteccion de columnas fallida */}
      {data && !data.mapping_ok && (
        <Card className="mt-4 border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] p-4">
          <p className="text-sm font-medium text-[var(--color-sumi)]">
            列を自動認識できませんでした
          </p>
          <p className="mt-1 text-xs text-[var(--color-sumi-soft)]">
            日付・金額の列が見つかりませんでした。CSVのヘッダー（取引日・出金金額・摘要など）をご確認のうえ、もう一度お試しください。
          </p>
          <button
            type="button"
            onClick={() => resetTo(null)}
            className="mt-3 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-4 py-2 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
          >
            別のファイルを選ぶ
          </button>
        </Card>
      )}

      {/* Preview */}
      {data && data.mapping_ok && (
        <PreviewTable
          data={data}
          selected={selected}
          allSelected={allSelected}
          onToggle={toggle}
          onToggleAll={toggleAll}
          accountOf={accountOf}
          onAccountChange={setAccount}
          onReset={() => resetTo(null)}
          selectedCount={[...selected].length}
          selectedTotal={selectedTotal}
          onCommit={handleCommit}
          committing={commit.isPending}
          readOnly={isReadOnly}
        />
      )}

      {/* Nota guia */}
      {!data && !committed && !error && !preview.isPending && (
        <div className="mt-2">
          <EmptyState
            icon="shield"
            title="入金（収入）は取り込みません"
            hint="この機能は経費（出金）の仕訳のみを作成します。確定前にすべて確認できます。重複は自動で検出され、二重登録を防ぎます。"
          />
        </div>
      )}
    </motion.div>
  );
}

/** Tabla de preview con seleccion, 勘定科目 editable y barra de confirmacion. */
function PreviewTable({
  data,
  selected,
  allSelected,
  onToggle,
  onToggleAll,
  accountOf,
  onAccountChange,
  onReset,
  selectedCount,
  selectedTotal,
  onCommit,
  committing,
  readOnly,
}: {
  data: CsvPreviewResponse;
  selected: Set<string>;
  allSelected: boolean;
  onToggle: (hash: string) => void;
  onToggleAll: () => void;
  accountOf: (row: CsvPreviewRow) => string;
  onAccountChange: (hash: string, code: string) => void;
  onReset: () => void;
  selectedCount: number;
  selectedTotal: number;
  onCommit: () => void;
  committing: boolean;
  readOnly: boolean;
}) {
  // Ordena: importables primero; dentro, por fecha.
  const rows = useMemo(
    () =>
      [...data.rows].sort((a, b) => {
        if (a.importable !== b.importable) return a.importable ? -1 : 1;
        return (a.date ?? "").localeCompare(b.date ?? "");
      }),
    [data.rows],
  );

  return (
    <div className="mt-5 pb-28">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <Label>検出結果</Label>
          <p className="mt-1 text-sm text-[var(--color-sumi-soft)]">
            {data.total_rows}件中 {data.importable_count}件が取り込み対象
            {data.duplicate_count > 0 && (
              <span className="text-[var(--color-kohaku)]">
                （{data.duplicate_count}件は重複）
              </span>
            )}
            <span className="tabular ml-1 opacity-70">· {data.encoding}</span>
          </p>
        </div>
        <button
          type="button"
          onClick={onReset}
          className="shrink-0 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3 py-1.5 text-xs font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
        >
          別のファイル
        </button>
      </div>

      <Card className="overflow-hidden">
        {/* Header de la tabla (全選択) — desktop */}
        <div className="hidden items-center gap-3 border-b border-[var(--color-hairline)] bg-[var(--color-paper-sink)] px-4 py-2.5 text-[11px] font-medium uppercase tracking-wider text-[var(--color-sumi-soft)] sm:flex">
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={onToggleAll}
              className="h-4 w-4 rounded accent-[var(--color-seiji)]"
              aria-label="全選択"
            />
            全選択
          </label>
          <span className="flex-1">取引先</span>
          <span className="w-24">日付</span>
          <span className="w-24 text-right">金額</span>
          <span className="w-32">勘定科目</span>
        </div>

        <ul className="divide-y divide-[var(--color-hairline)]">
          {rows.map((row) => {
            const checked = selected.has(row.dedup_hash);
            return (
              <li
                key={row.dedup_hash + row.index}
                className={`flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-3 ${row.importable ? "" : "opacity-55"}`}
              >
                <div className="flex items-center gap-3 sm:contents">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!row.importable || readOnly}
                    onChange={() => onToggle(row.dedup_hash)}
                    className="h-4 w-4 shrink-0 rounded accent-[var(--color-seiji)] disabled:opacity-40"
                    aria-label={`${row.vendor ?? "この行"}を選択`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium text-[var(--color-sumi)]">
                        {row.vendor ?? "（取引先 不明）"}
                      </p>
                      {row.is_duplicate && (
                        <span className="shrink-0 rounded-full bg-[var(--color-kohaku-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-kohaku)]">
                          重複
                        </span>
                      )}
                      {!row.importable && !row.is_duplicate && (
                        <span className="shrink-0 rounded-full bg-[var(--color-paper-sink)] px-2 py-0.5 text-[10px] text-[var(--color-sumi-soft)]">
                          対象外
                        </span>
                      )}
                    </div>
                    {row.skipped_reason && (
                      <p className="mt-0.5 text-[11px] text-[var(--color-sumi-soft)]">
                        {row.is_duplicate ? "既に登録済み" : row.skipped_reason}
                      </p>
                    )}
                  </div>
                </div>

                <span className="tabular ml-7 w-24 text-xs text-[var(--color-sumi-soft)] sm:ml-0">
                  {formatDate(row.date)}
                </span>
                <span className="tabular ml-7 w-24 text-right text-sm font-semibold text-[var(--color-sumi)] sm:ml-0">
                  {formatYen(row.total_amount)}
                </span>

                {/* 勘定科目 editable solo si es importable */}
                <div className="ml-7 w-32 sm:ml-0">
                  {row.importable ? (
                    <select
                      value={accountOf(row)}
                      onChange={(e) => onAccountChange(row.dedup_hash, e.target.value)}
                      disabled={readOnly}
                      className="w-full rounded-md border border-[var(--color-hairline)] bg-[var(--color-surface)] px-2 py-1 text-xs text-[var(--color-sumi)] focus:border-[var(--color-seiji)]"
                      aria-label={`${row.vendor ?? "この行"}の勘定科目`}
                    >
                      {EXPENSE_ACCOUNTS.map((a) => (
                        <option key={a.code} value={a.code}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="text-xs text-[var(--color-sumi-soft)]">—</span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </Card>

      {/* Barra fija de confirmacion */}
      {selectedCount > 0 && (
        <motion.div
          initial={{ y: 80, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          className="fixed inset-x-0 bottom-[calc(58px+env(safe-area-inset-bottom)+12px)] z-30 px-4 lg:bottom-4 lg:left-56"
        >
          <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-sumi)] px-4 py-3 shadow-[var(--shadow-lift)]">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-white">
                {selectedCount}件を選択中
              </p>
              <p className="tabular text-xs text-white/70">
                合計 {formatYen(selectedTotal)}
              </p>
            </div>
            <button
              type="button"
              onClick={onCommit}
              disabled={readOnly || committing}
              aria-label={`${selectedCount}件を仕訳トレイに追加`}
              className="flex shrink-0 items-center gap-2 whitespace-nowrap rounded-[var(--radius-pill)] bg-[var(--color-shuiro)] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-shuiro-deep)] disabled:opacity-70"
            >
              <Icon name="check" className="h-4 w-4" />
              {/* El conteo ya se ve en "○件を選択中": en movil acortamos a
                  "トレイに追加" para que no rompa a 2 lineas en 390px. */}
              {committing ? (
                "取り込み中…"
              ) : (
                <>
                  <span className="hidden sm:inline">{selectedCount}件を仕訳</span>
                  トレイに追加
                </>
              )}
            </button>
          </div>
        </motion.div>
      )}
    </div>
  );
}
