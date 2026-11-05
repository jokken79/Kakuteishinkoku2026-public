/**
 * 過去の申告 — archivo histórico de declaraciones anteriores ("dropbox inteligente").
 *
 * El owner sube el PDF de su 確定申告 de un año anterior; la app lo archiva
 * (電子帳簿保存法: 7 años) e intenta extraer los montos clave (所得/納付額/還付額)
 * por texto. La pantalla muestra:
 *
 *  - Zona drag/drop + selector de año (令和N) para subir un PDF.
 *  - Lista por año con los montos extraídos, editables si la extracción falló.
 *  - Comparación año a año: gráfico de la evolución del 所得 y del impuesto.
 *  - Ver/descargar el PDF guardado. Estado vacío que guía.
 *
 * Mobile-first, a11y, design system "Calma fiscal". La UI permanece en japonés
 * con la capa de ayuda ES (subtítulos/glosas) cuando está activa.
 */
import { useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  usePastFilings,
  useUploadPastFiling,
  usePatchPastFiling,
  useDeletePastFiling,
} from "../lib/hooks";
import { ApiError, pastFilingPdfUrl, type PastFiling } from "../lib/api";
import { formatYen, toReiwa } from "../lib/format";
import { Card, EmptyState, Label } from "../components/ui";
import { Icon } from "../components/Icon";
import { HelpSubtitle, HelpTerm } from "../components/HelpTerm";
import { screenVariants, staggerContainer, staggerItem } from "../variants/layoutVariants";

/** Años 令和 ofrecidos en el selector (令和6 → 令和1). */
const YEAR_OPTIONS: number[] = [2024, 2023, 2022, 2021, 2020, 2019];

const CHART_COLORS = {
  income: "#3e9b86", // seiji — 所得
  tax: "#dda24a", // kohaku — 税
  grid: "#ece8e0", // hairline
  axis: "#5a6175", // sumi-soft
};

export function PastFilingsScreen() {
  const { data, isLoading } = usePastFilings();
  const upload = useUploadPastFiling();
  const [year, setYear] = useState<number>(YEAR_OPTIONS[0]);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const filings = data?.filings ?? [];
  const comparison = data?.comparison ?? [];

  const handleFile = (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setNotice(null);
    upload.mutate(
      { file, year },
      {
        onSuccess: (res) => {
          if (res.duplicate) {
            setNotice("この申告書はすでに保存されています。");
          } else if (!res.extracted) {
            setNotice("PDFから金額を読み取れませんでした。下の一覧で手入力してください。");
          }
        },
        onError: (err) =>
          setError(
            err instanceof ApiError
              ? err.message
              : "アップロードに失敗しました。もう一度お試しください。",
          ),
      },
    );
  };

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-3xl px-4 py-6 sm:px-8 sm:py-10"
    >
      {/* Encabezado */}
      <div className="mb-6">
        <h2 className="text-xl font-bold text-[var(--color-sumi)]">
          過去の申告
          <HelpTerm term="過去の申告" size="md" />
        </h2>
        <HelpSubtitle className="mt-1">
          Declaraciones anteriores — archivá tus 確定申告 de años pasados y comparálos.
        </HelpSubtitle>
        <p className="mt-2 text-sm leading-relaxed text-[var(--color-sumi-soft)]">
          過去の確定申告書（PDF）をアップロードして保存・比較できます。
        </p>
      </div>

      {/* Zona de subida */}
      <input
        ref={fileInput}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />

      <Card as="section" className="p-5">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <Label>年度</Label>
            <HelpSubtitle className="mb-1.5">Año fiscal del PDF</HelpSubtitle>
            <div className="relative inline-block">
              <select
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                aria-label="申告書の年度を選択"
                className="appearance-none rounded-[var(--radius-pill)] border border-[var(--color-hairline)] bg-[var(--color-surface)] py-2 pl-4 pr-9 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)] focus:border-[var(--color-seiji)]"
              >
                {YEAR_OPTIONS.map((y) => (
                  <option key={y} value={y}>
                    {toReiwa(y)}（{y}年分）
                  </option>
                ))}
              </select>
              <Icon
                name="arrow"
                className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 rotate-90 text-[var(--color-sumi-soft)]"
              />
            </div>
          </div>
        </div>

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
          className={`flex flex-col items-center rounded-[var(--radius-card)] border-2 border-dashed p-7 text-center transition-colors ${
            dragging
              ? "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)]"
              : "border-[var(--color-hairline)]"
          }`}
        >
          {upload.isPending ? (
            <div className="flex flex-col items-center py-4">
              <motion.div
                className="h-11 w-11 rounded-full border-2 border-[var(--color-hairline)] border-t-[var(--color-seiji)]"
                animate={{ rotate: 360 }}
                transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
              />
              <p className="mt-3 text-sm text-[var(--color-sumi-soft)]">
                読み取り中…
              </p>
            </div>
          ) : (
            <>
              <div className="mb-3 grid h-14 w-14 place-items-center rounded-full bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
                <Icon name="file" className="h-6 w-6" />
              </div>
              <p className="text-base font-medium text-[var(--color-sumi)]">
                確定申告書をアップロード
              </p>
              <HelpSubtitle className="mt-1">
                Arrastrá el PDF o elegilo abajo
              </HelpSubtitle>
              <p className="mt-1.5 max-w-sm text-sm text-[var(--color-sumi-soft)]">
                {toReiwa(year)}分のPDFをここにドラッグするか、下のボタンから選んでください。
              </p>
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                className="mt-4 flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
              >
                <Icon name="upload" className="h-4 w-4" />
                PDFを選択
              </button>
            </>
          )}
        </div>

        {/* Nota 電子帳簿保存法 */}
        <div className="mt-4 flex items-start gap-2.5 rounded-lg bg-[var(--color-paper-sink)] p-3">
          <Icon
            name="shield"
            className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-seiji)]"
          />
          <p className="text-xs leading-relaxed text-[var(--color-sumi-soft)]">
            アップロードしたPDFは端末内に保存され、外部に送信されません。
            <HelpTerm term="電子帳簿保存法" />
            電子帳簿保存法により、申告書類は7年間保存することが推奨されます。
            <HelpSubtitle className="mt-0.5">
              Los PDFs se guardan en el equipo (privado). La ley 電子帳簿保存法
              recomienda conservarlos 7 años.
            </HelpSubtitle>
          </p>
        </div>
      </Card>

      {/* Avisos */}
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
      {notice && !error && (
        <Card className="mt-4 border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] p-4">
          <p className="text-sm text-[var(--color-sumi)]">{notice}</p>
        </Card>
      )}

      {/* Comparación año a año */}
      {comparison.length >= 1 && (
        <ComparisonChart comparison={comparison} />
      )}

      {/* Lista de declaraciones */}
      <div className="mt-6">
        <div className="mb-3 flex items-baseline justify-between">
          <div>
            <Label>保存済みの申告</Label>
            <HelpSubtitle>Declaraciones guardadas</HelpSubtitle>
          </div>
          {filings.length > 0 && (
            <span className="text-xs text-[var(--color-sumi-soft)]">
              {filings.length}件
            </span>
          )}
        </div>

        {isLoading ? (
          <p className="py-8 text-center text-sm text-[var(--color-sumi-soft)]">
            読み込み中…
          </p>
        ) : filings.length === 0 ? (
          <Card>
            <EmptyState
              icon="file"
              title="過去の申告書をアップロード"
              hint="まだ保存された申告書はありません。上のエリアからPDFを追加すると、ここに年度ごとに一覧表示され、年度比較ができます。"
            />
          </Card>
        ) : (
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="space-y-3"
          >
            {filings.map((filing) => (
              <FilingRow key={filing.id} filing={filing} />
            ))}
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}

// --- Gráfico de comparación año a año --------------------------------------

interface ComparisonPoint {
  year: number;
  total_income: number | null;
  net_tax: number | null;
}

function ComparisonChart({ comparison }: { comparison: ComparisonPoint[] }) {
  // Solo tiene sentido graficar puntos con algún monto.
  const points = useMemo(
    () =>
      comparison
        .filter((p) => p.total_income !== null || p.net_tax !== null)
        .map((p) => ({
          year: p.year,
          label: toReiwa(p.year),
          所得: p.total_income ?? undefined,
          税: p.net_tax ?? undefined,
        })),
    [comparison],
  );

  if (points.length === 0) {
    return (
      <Card className="mt-6 p-5">
        <Label>年度比較</Label>
        <HelpSubtitle>Comparación año a año</HelpSubtitle>
        <p className="mt-3 text-sm text-[var(--color-sumi-soft)]">
          金額が読み取れた申告がまだありません。一覧で金額を入力すると、ここに推移グラフが表示されます。
        </p>
      </Card>
    );
  }

  const single = points.length === 1;

  return (
    <Card className="mt-6 p-5">
      <div className="mb-1 flex items-center justify-between">
        <div>
          <Label>年度比較</Label>
          <HelpSubtitle>Comparación año a año (所得 / 税)</HelpSubtitle>
        </div>
        <div className="flex items-center gap-3 text-xs text-[var(--color-sumi-soft)]">
          <span className="inline-flex items-center gap-1.5">
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: CHART_COLORS.income }}
              aria-hidden
            />
            所得
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: CHART_COLORS.tax }}
              aria-hidden
            />
            税
          </span>
        </div>
      </div>

      {single ? (
        <SingleYearSummary point={points[0]} />
      ) : (
        <div className="mt-3 w-full">
          {/* height explícito (no "100%"): evita que ResponsiveContainer monte
              con width(-1)/height(-1) en el primer frame, antes de medir el padre. */}
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={points} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
              <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: CHART_COLORS.axis }}
                axisLine={{ stroke: CHART_COLORS.grid }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: CHART_COLORS.axis }}
                axisLine={false}
                tickLine={false}
                width={56}
                tickFormatter={(v: number) =>
                  Math.abs(v) >= 10000 ? `${Math.round(v / 10000)}万` : String(v)
                }
              />
              <Tooltip
                formatter={(value, name) => [
                  formatYen(typeof value === "number" ? value : Number(value)),
                  name,
                ]}
                contentStyle={{
                  borderRadius: 12,
                  border: "1px solid #ece8e0",
                  fontSize: 12,
                }}
              />
              <Line
                type="monotone"
                dataKey="所得"
                stroke={CHART_COLORS.income}
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="税"
                stroke={CHART_COLORS.tax}
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

function SingleYearSummary({
  point,
}: {
  point: { label: string; 所得?: number; 税?: number };
}) {
  return (
    <div className="mt-3">
      <p className="text-sm text-[var(--color-sumi-soft)]">
        申告が1件のため、推移グラフは2件以上で表示されます。
      </p>
      <HelpSubtitle className="mt-0.5">
        Con 2 o más años se dibuja el gráfico de evolución.
      </HelpSubtitle>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-[var(--color-paper-sink)] p-3">
          <p className="text-[11px] font-medium uppercase tracking-[0.1em] text-[var(--color-sumi-soft)]">
            {point.label}・所得
          </p>
          <p className="tabular mt-0.5 text-lg font-bold text-[var(--color-sumi)]">
            {point.所得 === undefined ? "—" : formatYen(point.所得)}
          </p>
        </div>
        <div className="rounded-lg bg-[var(--color-paper-sink)] p-3">
          <p className="text-[11px] font-medium uppercase tracking-[0.1em] text-[var(--color-sumi-soft)]">
            {point.label}・税
          </p>
          <p className="tabular mt-0.5 text-lg font-bold text-[var(--color-sumi)]">
            {point.税 === undefined ? "—" : formatYen(point.税)}
          </p>
        </div>
      </div>
    </div>
  );
}

// --- Fila de una declaración histórica -------------------------------------

function FilingRow({ filing }: { filing: PastFiling }) {
  const patch = usePatchPastFiling();
  const del = useDeletePastFiling();
  const [editing, setEditing] = useState(false);
  const [income, setIncome] = useState(filing.total_income?.toString() ?? "");
  const [taxPaid, setTaxPaid] = useState(filing.tax_paid?.toString() ?? "");
  const [taxRefund, setTaxRefund] = useState(filing.tax_refund?.toString() ?? "");

  const isRefund = (filing.tax_refund ?? 0) > 0;
  const needsReview = filing.extraction_source === "auto" && filing.total_income === null;

  const parseAmount = (raw: string): number | null => {
    const digits = raw.replace(/[^\d]/g, "");
    return digits ? Number(digits) : null;
  };

  const save = () => {
    patch.mutate(
      {
        id: filing.id,
        patch: {
          total_income: parseAmount(income),
          tax_paid: parseAmount(taxPaid),
          tax_refund: parseAmount(taxRefund),
        },
      },
      { onSuccess: () => setEditing(false) },
    );
  };

  return (
    <motion.div variants={staggerItem}>
      <Card className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
              <Icon name="file" className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm font-bold text-[var(--color-sumi)]">
                {toReiwa(filing.year)}
                <span className="ml-1.5 text-xs font-normal text-[var(--color-sumi-soft)]">
                  {filing.year}年分
                </span>
              </p>
              <p className="mt-0.5 truncate text-xs text-[var(--color-sumi-soft)]">
                {filing.original_filename ?? "—"}
              </p>
              {filing.tax_office && (
                <p className="mt-0.5 text-xs text-[var(--color-sumi-soft)]">
                  {filing.tax_office}
                </p>
              )}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            <a
              href={pastFilingPdfUrl(filing.id)}
              target="_blank"
              rel="noopener noreferrer"
              title="PDFを開く"
              aria-label="保存されたPDFを開く"
              className="grid h-8 w-8 place-items-center rounded-[var(--radius-pill)] border border-[var(--color-hairline)] text-[var(--color-sumi-soft)] transition-colors hover:bg-[var(--color-paper-sink)]"
            >
              <Icon name="file" className="h-4 w-4" />
            </a>
            <button
              type="button"
              onClick={() => setEditing((v) => !v)}
              title="金額を編集"
              aria-label="抽出された金額を編集"
              className="grid h-8 w-8 place-items-center rounded-[var(--radius-pill)] border border-[var(--color-hairline)] text-[var(--color-sumi-soft)] transition-colors hover:bg-[var(--color-paper-sink)]"
            >
              <Icon name="edit" className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => {
                if (window.confirm(`${toReiwa(filing.year)}の申告書を削除しますか？`)) {
                  del.mutate(filing.id);
                }
              }}
              title="削除"
              aria-label="この申告を削除"
              className="grid h-8 w-8 place-items-center rounded-[var(--radius-pill)] border border-[var(--color-hairline)] text-[var(--color-sumi-soft)] transition-colors hover:border-[var(--color-kohaku)] hover:text-[var(--color-kohaku)]"
            >
              <Icon name="archive" className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Montos */}
        {editing ? (
          <div className="mt-4 space-y-3 border-t border-[var(--color-hairline)] pt-4">
            <AmountField
              label="所得金額"
              term="所得"
              value={income}
              onChange={setIncome}
            />
            <AmountField
              label="納付税額"
              term="納付"
              value={taxPaid}
              onChange={setTaxPaid}
            />
            <AmountField
              label="還付金額"
              term="還付"
              value={taxRefund}
              onChange={setTaxRefund}
            />
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-4 py-2 text-sm font-medium text-[var(--color-sumi-soft)] transition-colors hover:bg-[var(--color-paper-sink)]"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={save}
                disabled={patch.isPending}
                className="rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                保存
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-[var(--color-hairline)] pt-3 sm:grid-cols-3">
            <AmountReadout label="所得" term="所得" value={filing.total_income} />
            {isRefund ? (
              <AmountReadout
                label="還付額"
                term="還付"
                value={filing.tax_refund}
                positive
              />
            ) : (
              <AmountReadout label="納付額" term="納付" value={filing.tax_paid} />
            )}
            <div>
              <p className="text-[11px] text-[var(--color-sumi-soft)]">読み取り</p>
              <p className="mt-0.5 text-sm font-medium text-[var(--color-sumi)]">
                {filing.extraction_source === "manual" ? "手入力" : "自動"}
              </p>
            </div>
          </div>
        )}

        {needsReview && !editing && (
          <div className="mt-3 flex items-center gap-2 rounded-lg bg-[var(--color-kohaku-soft)] px-3 py-2">
            <Icon name="edit" className="h-3.5 w-3.5 text-[var(--color-kohaku)]" />
            <p className="text-xs text-[var(--color-sumi)]">
              金額を自動で読み取れませんでした。鉛筆アイコンから手入力してください。
            </p>
          </div>
        )}
      </Card>
    </motion.div>
  );
}

function AmountReadout({
  label,
  term,
  value,
  positive = false,
}: {
  label: string;
  term: string;
  value: number | null;
  positive?: boolean;
}) {
  return (
    <div>
      <p className="inline-flex items-center text-[11px] text-[var(--color-sumi-soft)]">
        {label}
        <HelpTerm term={term} />
      </p>
      <p
        className={`tabular mt-0.5 text-sm font-medium ${positive ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]"}`}
      >
        {value === null ? "—" : formatYen(value)}
      </p>
    </div>
  );
}

function AmountField({
  label,
  term,
  value,
  onChange,
}: {
  label: string;
  term: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="inline-flex items-center text-xs font-medium text-[var(--color-sumi-soft)]">
        {label}
        <HelpTerm term={term} />
      </span>
      <div className="mt-1 flex items-center rounded-[var(--radius-pill)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 focus-within:border-[var(--color-seiji)]">
        <span className="text-sm text-[var(--color-sumi-soft)]">¥</span>
        <input
          type="text"
          inputMode="numeric"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="0"
          className="tabular w-full bg-transparent py-2 pl-1.5 text-right text-sm text-[var(--color-sumi)] outline-none"
        />
      </div>
    </label>
  );
}
