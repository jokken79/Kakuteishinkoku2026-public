/**
 * 確定申告 (申告書の生成). Revision del calculo final + checklist de prontitud +
 * descarga de formularios (PDF / .xtx / CSV) + guia e-Tax. Reemplaza el
 * placeholder "準備中". Datos reales del backend (`/filing/draft`).
 *
 * El resultado se destaca como el dashboard: 納付 en sumi, 還付 en seiji.
 */
import { motion } from "framer-motion";
import { useState } from "react";
import {
  filingCsvUrl,
  filingOfficialPackageUrl,
  filingPdfUrl,
  ApiError,
  type FilingPdfForm,
  type FilingSummary,
} from "../lib/api";
import { useActiveYear, useActiveYearLock, useFilingDraft } from "../lib/hooks";
import { useUiStore } from "../lib/store";
import { formatAmount, formatYen } from "../lib/format";
import { Card, ErrorState, Label, Skeleton } from "../components/ui";
import { EstimatedPrepayment } from "../components/EstimatedPrepayment";
import { FilingTypeByYear } from "../components/FilingTypeByYear";
import { XtxReviewForm } from "../components/XtxReviewForm";
import { Icon, type IconName } from "../components/Icon";
import { HelpSubtitle, HelpTerm } from "../components/HelpTerm";
import {
  heroAmountVariants,
  screenVariants,
  staggerContainer,
  staggerItem,
} from "../variants/layoutVariants";

export function FilingScreen() {
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  const year = useActiveYear();
  const { isReadOnly } = useActiveYearLock();
  const { data: filing, isLoading, isError, error, refetch } = useFilingDraft();
  const [staleYear, setStaleYear] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  async function refreshAfterFilingTypeChange() {
    const requestedYear = year;
    setStaleYear(requestedYear);
    setRefreshing(true);
    try {
      const result = await refetch();
      if (!result.isError && result.data?.year === requestedYear) {
        setStaleYear((current) => current === requestedYear ? null : current);
      }
    } catch {
      // El aviso permanece visible hasta un recálculo correcto.
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-3xl px-4 py-6 sm:px-8 sm:py-10"
    >
      <header className="mb-6 flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
          <Icon name="file" className="h-5 w-5" />
        </div>
        <div>
          <h2 className="flex items-center text-xl font-bold text-[var(--color-sumi)]">
            確定申告
            <HelpTerm term="確定申告" size="md" />
          </h2>
          <HelpSubtitle term="確定申告" />
          <p className="text-sm text-[var(--color-sumi-soft)]">
            申告書の生成（PDF / CSV）
          </p>
        </div>
      </header>

      {isLoading && <FilingSkeleton />}

      {isError && (
        <Card className="p-2">
          <ErrorState
            message={
              error instanceof Error
                ? error.message
                : "申告書の計算に失敗しました。"
            }
            onRetry={() => {
              if (staleYear === year) void refreshAfterFilingTypeChange();
              else void refetch();
            }}
          />
          {error instanceof ApiError && error.code === "journal_origin_unknown" && <JournalOriginReview key={year} year={year} />}
        </Card>
      )}

      {filing && (
        <div className="space-y-5">
          {isReadOnly && <Card className="p-4 text-sm">Este ejercicio está cerrado o presentado. La vista consulta los asientos existentes sin regenerarlos; comprueba la declaración presentada y sus documentos originales.</Card>}
          <FilingTypeByYear key={filing.year} year={filing.year} readOnly={isReadOnly} onSaved={() => { void refreshAfterFilingTypeChange(); }} />
          <EstimatedPrepayment year={filing.year} />
          {filing.year === 2026 && (
            <Card className="p-4 text-sm leading-relaxed">
              令和8年分の計算は概算です。一部の控除と住民税は未対応・要確認です。
              この画面の金額だけで申告しないでください。
              <p className="mt-1">Estimación provisional: algunas deducciones y el 住民税 requieren revisión.</p>
            </Card>
          )}
          {filing.income_breakdown.some((item) => item.kind === "fudosan" && item.amount < 0) && (
            <Card className="p-4 text-sm">
              <p role="alert">Pérdida inmobiliaria: esta estimación no identifica automáticamente las excepciones de 損益通算, como ciertos intereses de préstamos para terrenos. Revisa los importes antes de presentar.</p>
            </Card>
          )}
          {filing.pending_count > 0 && (
            <PendingNotice
              count={filing.pending_count}
              onOpenTray={() => setActiveSection("journal-tray")}
            />
          )}

          {staleYear === filing.year ? (
            <Card className="p-4 text-sm">
              <p role="alert">La modalidad se guardó, pero el cálculo anterior ya no es válido. Actualiza la declaración antes de usar sus importes o descargas.</p>
              <button type="button" disabled={refreshing} onClick={() => { void refreshAfterFilingTypeChange(); }} className="mt-2 rounded bg-[var(--color-sumi)] px-4 py-2 text-white disabled:opacity-50">
                {refreshing ? "Actualizando…" : "Volver a calcular"}
              </button>
            </Card>
          ) : (
            <>
              <ReviewCard filing={filing} />
              <ResidentTaxCard filing={filing} />
              <ChecklistCard filing={filing} />
              <DownloadsCard filing={filing} />
              {filing.year === 2025 && <EtaxGuideCard />}
            </>
          )}
        </div>
      )}
    </motion.div>
  );
}

type UnidentifiedJournal = {
  id: string; fingerprint: string; date: string; description: string | null; transaction_id: string | null;
  lines: { side: string; account_code: string; account_name: string; amount: number }[];
};

function JournalOriginReview({ year }: { year: number }) {
  const [entries, setEntries] = useState<UnidentifiedJournal[] | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [backupConfirmed, setBackupConfirmed] = useState(false);
  async function load() {
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(`/api/v1/filing/journal-review?year=${year}`, { cache: "no-store" });
      if (!response.ok) throw new Error("No se pudo cargar la lista de asientos.");
      const result = await response.json() as { year: number; entries: UnidentifiedJournal[] };
      if (result.year !== year) throw new Error("El ejercicio recibido no coincide.");
      setEntries(result.entries);
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : "No se pudo cargar la lista.");
    } finally {
      setLoading(false);
    }
  }
  async function choose(entry: UnidentifiedJournal, origin: "manual" | "projection") {
    if (!backupConfirmed || loading) return;
    const explanation = origin === "manual"
      ? "Se conservará como asiento manual. Si también representa una transacción que la app regenera, podría contarse dos veces."
      : "Se marcará como proyección. En el próximo cálculo la app eliminará este asiento y regenerará los que correspondan a los datos actuales.";
    if (!window.confirm(`${explanation} Confirma que revisaste este asiento y tienes una copia de seguridad. ¿Continuar?`)) return;
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(`/api/v1/filing/journal-review/${entry.id}/origin?year=${year}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ origin, fingerprint: entry.fingerprint, backup_confirmed: true }),
      });
      if (!response.ok) throw new Error("No se pudo guardar la decisión. Actualiza la lista y revisa el estado del ejercicio.");
      setEntries((current) => current?.filter((item) => item.id !== entry.id) ?? null);
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : "No se pudo guardar la decisión.");
    } finally {
      setLoading(false);
    }
  }
  return <section className="m-3 rounded-lg border border-[var(--color-hairline)] p-4">
    <p className="text-sm">Esta consulta solo muestra los asientos del ejercicio {year}; no los modifica. Compara las líneas con tus documentos y haz una copia de seguridad antes de cualquier corrección.</p>
    <button type="button" disabled={loading} onClick={() => void load()} className="mt-3 underline disabled:opacity-50">{loading ? "Cargando…" : "Ver asientos sin identificar"}</button>
    {message && <p role="alert" className="mt-2">{message}</p>}
    {entries && entries.length > 0 && <label className="mt-3 flex items-start gap-2 text-sm"><input type="checkbox" checked={backupConfirmed} onChange={(event) => setBackupConfirmed(event.target.checked)} />He hecho una copia de seguridad y revisaré cada asiento antes de elegir su origen.</label>}
    {entries && <ul className="mt-3 space-y-3">{entries.map((entry) => <li key={entry.id} className="rounded border border-[var(--color-hairline)] p-3 text-sm">
      <p>{entry.date} · {entry.description || "Sin descripción"}</p>
      <p className="text-xs">ID: {entry.id} · {entry.transaction_id ? `Comprobante vinculado: ${entry.transaction_id}` : "Sin comprobante vinculado"}</p>
      <ul>{entry.lines.map((line, index) => <li key={`${line.account_code}-${index}`}>{line.side} · {line.account_code} {line.account_name} · {formatYen(line.amount)}</li>)}</ul>
      <p className="mt-2 text-xs">Manual: se conserva y podría duplicar una transacción. Proyección: será reemplazado al recalcular. Si no lo sabes, no elijas todavía.</p>
      <div className="mt-2 flex flex-wrap gap-3"><button type="button" disabled={!backupConfirmed || loading} onClick={() => void choose(entry, "manual")} className="underline disabled:opacity-50">Conservar como manual</button>
      <button type="button" disabled={!backupConfirmed || loading} onClick={() => void choose(entry, "projection")} className="underline disabled:opacity-50">Marcar como proyección</button></div>
    </li>)}</ul>}
    {entries?.length === 0 && <p className="mt-2 text-sm">No quedan asientos sin identificar. Vuelve a intentar el cálculo.</p>}
    <p className="mt-3 text-sm">La app no identifica automáticamente el origen. La decisión se registra para auditoría y no cambia las líneas en este paso.</p>
  </section>;
}

// --- Aviso de 仕訳 pendientes -----------------------------------------------

function PendingNotice({
  count,
  onOpenTray,
}: {
  count: number;
  onOpenTray: () => void;
}) {
  return (
    <Card className="flex items-start gap-3 border-[var(--color-kohaku)] p-4">
      <div className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[var(--color-kohaku-soft)] text-[var(--color-kohaku)]">
        <Icon name="tray" className="h-5 w-5" />
      </div>
      <div className="flex-1">
        <p className="text-sm font-medium text-[var(--color-sumi)]">
          未確認の仕訳が{count}件あります
        </p>
        <p className="mt-1 text-sm leading-relaxed text-[var(--color-sumi-soft)]">
          申告書を生成する前に、仕訳トレイで取引を確認することをおすすめします。
          確認すると金額が更新されます。
        </p>
        <button
          type="button"
          onClick={onOpenTray}
          className="mt-3 inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3.5 py-1.5 text-xs font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
        >
          仕訳トレイへ
          <Icon name="arrow" className="h-3.5 w-3.5" />
        </button>
      </div>
    </Card>
  );
}

// --- Revision del calculo ---------------------------------------------------

function ReviewCard({ filing }: { filing: FilingSummary }) {
  const isRefund = filing.is_refund;
  const filingLabels: Record<string, string> = {
    aoiro_65: "青色申告・65万円の区分",
    aoiro_55: "青色申告・55万円の区分",
    aoiro_10: "青色申告・10万円の区分",
    shiroiro: "白色申告",
  };
  return (
    <Card className="p-5 sm:p-6">
      <Label>申告内容の確認</Label>
      <div className="mt-3 rounded-lg bg-[var(--color-kohaku-soft)] p-3 text-sm leading-relaxed text-[var(--color-sumi)]">
        <p>申告区分: {filingLabels[filing.filing_type] ?? "要確認"} · 青色申告特別控除: ¥{formatAmount(filing.aoiro_deduction)}</p>
        <p className="mt-1">Modalidad configurada y deducción aplicada en este cálculo. La app no confirma que cumplas los requisitos; revisa la modalidad, los libros y la forma y plazo de presentación.</p>
        <a className="mt-1 inline-block underline" href="https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/2072.htm" target="_blank" rel="noreferrer">Requisitos de 国税庁</a>
      </div>

      {/* Hero: 納付額 / 還付金 */}
      <motion.div
        variants={heroAmountVariants}
        initial="hidden"
        animate="visible"
        className="mt-3 flex items-end gap-2"
      >
        <span className="text-sm text-[var(--color-sumi-soft)]">
          {isRefund ? "還付される税金" : "納める税金"}
        </span>
      </motion.div>
      <div className="mt-1 flex items-end gap-2">
        <span
          className={`tabular text-3xl font-medium leading-none ${isRefund ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]"}`}
        >
          ¥
        </span>
        <span
          className={`tabular text-5xl font-bold leading-none tracking-tight sm:text-6xl ${isRefund ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]"}`}
        >
          {formatAmount(filing.final_amount)}
        </span>
        {isRefund && (
          <span className="mb-1 ml-1 rounded-[var(--radius-pill)] bg-[var(--color-seiji-soft)] px-2.5 py-1 text-xs font-medium text-[var(--color-seiji)]">
            戻ってくる見込み
          </span>
        )}
      </div>

      {/* Cascada del calculo */}
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="mt-6 space-y-0.5"
      >
        <CalcRow
          label={filing.filing_type.startsWith("aoiro_") ? "事業所得（青色申告特別控除後）" : "事業所得"}
          value={filing.business_income}
          term="事業所得"
        />
        <CalcRow label="合計所得金額" value={filing.total_income} strong />
        <CalcRow
          label="所得控除の合計"
          value={filing.total_income_deductions}
          minus
          term="所得控除"
        />
        <CalcRow
          label="課税所得金額"
          value={filing.taxable_income}
          strong
          term="課税所得"
        />
        <CalcDivider />
        <CalcRow
          label="所得税（基準額）"
          value={filing.income_tax_base}
          term="所得税"
        />
        <CalcRow
          label="復興特別所得税"
          value={filing.reconstruction_tax}
          term="復興特別所得税"
        />
        <CalcRow label="所得税及び復興特別所得税" value={filing.total_tax} strong />
        <CalcRow
          label="源泉徴収・予定納税"
          value={filing.withholding_total}
          minus
          term="源泉徴収"
        />
        <CalcDivider />
        <CalcRow
          label={isRefund ? "還付金" : "納付額"}
          value={Math.abs(filing.final_amount)}
          strong
          accent={isRefund ? "seiji" : "sumi"}
          term={isRefund ? "還付" : "納付"}
        />
      </motion.div>

      {/* Que entro */}
      <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <MiniStat
          icon="check"
          label="確認済みの仕訳"
          value={`${filing.confirmed_count}件`}
          sub={`経費 ${formatYen(filing.confirmed_expense_total)}`}
        />
        <MiniStat
          icon="compass"
          label="適用した控除"
          value={`${filing.deductions_applied.length}件`}
          sub={`控除合計 ${formatYen(filing.total_income_deductions)}`}
        />
      </div>

      <p className="mt-4 flex items-center gap-1.5 text-xs text-[var(--color-sumi-soft)]">
        <Icon
          name="check"
          className={`h-3.5 w-3.5 ${filing.bs_balanced ? "text-[var(--color-seiji)]" : "text-[var(--color-kohaku)]"}`}
        />
        貸借対照表の整合性：
        {filing.bs_balanced ? "一致（資産 ＝ 負債＋資本）" : "不一致（要確認）"}
      </p>
    </Card>
  );
}

// --- Estimacion del 住民税 (impuesto de residencia, pago futuro) ------------

function ResidentTaxCard({ filing }: { filing: FilingSummary }) {
  const rt = filing.resident_tax;
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex items-center justify-between">
        <Label>
          <span className="inline-flex items-center">
            住民税の見込み
            <HelpTerm term="住民税" />
          </span>
        </Label>
        <span className="rounded-[var(--radius-pill)] bg-[var(--color-kohaku-soft)] px-2.5 py-1 text-[10px] font-medium text-[var(--color-kohaku)]">
          翌年6月〜の支払い
        </span>
      </div>

      {/* Mensaje pedagogico (persona gentleman): que es y por que NO es 還付. */}
      <p className="mt-3 text-sm leading-relaxed text-[var(--color-sumi-soft)]">
        所得税（国の税金）とは別に、お住まいの市区町村と県へ納める地方税です。
        <span className="font-medium text-[var(--color-sumi)]">
          来年の6月〜翌5月にかけて支払います
        </span>
        （還付ではなく、これからの支払いです）。所得税とは
        <HelpTerm term="基礎控除" />
        などの控除額が異なるため、課税所得も別に計算します。
      </p>

      {/* Hero: 住民税 total estimado */}
      <div className="mt-5 flex items-end gap-2">
        <span className="text-sm text-[var(--color-sumi-soft)]">
          住民税の見込み額
        </span>
      </div>
      <div className="mt-1 flex items-end gap-2">
        <span className="tabular text-2xl font-medium leading-none text-[var(--color-sumi)]">
          ¥
        </span>
        <span className="tabular text-4xl font-bold leading-none tracking-tight text-[var(--color-sumi)] sm:text-5xl">
          {formatAmount(rt.total)}
        </span>
        <span className="mb-1 ml-1 text-xs text-[var(--color-sumi-soft)]">
          （概算）
        </span>
      </div>

      {/* Cascada del calculo del 住民税 */}
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="mt-5 space-y-0.5"
      >
        <CalcRow label="合計所得金額" value={rt.total_income} />
        <CalcRow
          label="課税所得（住民税）"
          value={rt.taxable_income}
          strong
          term="課税所得"
        />
        <CalcDivider />
        <CalcRow
          label="所得割（県民税 4%）"
          value={rt.shotokuwari_prefectural}
          term="県民税"
        />
        <CalcRow
          label="所得割（市民税 6%）"
          value={rt.shotokuwari_municipal}
          term="市民税"
        />
        <CalcRow label="所得割 合計" value={rt.shotokuwari_total} strong term="所得割" />
        <CalcRow label="均等割" value={rt.kintowari_total} term="均等割" />
        <CalcRow
          label="調整控除"
          value={rt.chosei_kojo}
          minus
          term="調整控除"
        />
        <CalcDivider />
        <CalcRow
          label="住民税（見込み）"
          value={rt.total}
          strong
          accent="sumi"
          term="住民税"
        />
      </motion.div>

      {/* Nota del 均等割 (desglose) + 森林環境税 */}
      <p className="mt-4 text-xs leading-relaxed text-[var(--color-sumi-soft)]">
        均等割の内訳：県民税 {formatYen(rt.kintowari_prefectural)} ＋ 市民税{" "}
        {formatYen(rt.kintowari_municipal)} ＋ 森林環境税
        <HelpTerm term="森林環境税" />{" "}
        {formatYen(rt.forest_environment_tax)}（愛知県内の標準額を使用。自治体により異なります）。
      </p>

      {/* Disclaimer: estimacion, no 税理士 */}
      <div className="mt-4 flex items-start gap-2.5 rounded-[var(--radius-card)] bg-[var(--color-paper-sink)] p-3.5">
        <Icon
          name="shield"
          className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-sumi-soft)]"
        />
        <p className="text-xs leading-relaxed text-[var(--color-sumi-soft)]">
          これは概算の見込み額です。実際の住民税は市区町村が決定・通知します。障害者控除・保険料控除・配偶者控除・寄附金控除などは所得税と住民税で異なり、この概算には正確に反映されない場合があります。非課税限度額や各種軽減も未対応です。
        </p>
      </div>
    </Card>
  );
}

function CalcRow({
  label,
  value,
  strong = false,
  minus = false,
  accent,
  term,
}: {
  label: string;
  value: number;
  strong?: boolean;
  minus?: boolean;
  accent?: "seiji" | "sumi";
  /** Termino del glosario a explicar en ES (opcional; muestra un (?)). */
  term?: string;
}) {
  const color =
    accent === "seiji" ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]";
  return (
    <motion.div
      variants={staggerItem}
      className="flex items-center justify-between gap-2 border-b border-[var(--color-hairline)] py-2 last:border-b-0"
    >
      <span
        className={`flex min-w-0 items-center text-sm text-[var(--color-sumi)] ${strong ? "font-medium" : ""}`}
      >
        <span className="min-w-0">{label}</span>
        {term && <HelpTerm term={term} />}
      </span>
      <span
        className={`tabular ${strong ? "text-base font-bold" : "text-sm"} ${color}`}
      >
        {minus ? "−" : ""}
        {formatYen(value)}
      </span>
    </motion.div>
  );
}

function CalcDivider() {
  return <div className="my-1 h-px bg-[var(--color-sumi)] opacity-10" />;
}

function MiniStat({
  icon,
  label,
  value,
  sub,
}: {
  icon: IconName;
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="rounded-[var(--radius-card)] bg-[var(--color-paper-sink)] p-3.5">
      <div className="mb-1 flex items-center gap-1.5">
        <Icon name={icon} className="h-4 w-4 text-[var(--color-sumi-soft)]" />
        <span className="text-xs text-[var(--color-sumi-soft)]">{label}</span>
      </div>
      <p className="tabular text-xl font-bold text-[var(--color-sumi)]">{value}</p>
      <p className="text-xs text-[var(--color-sumi-soft)]">{sub}</p>
    </div>
  );
}

// --- Checklist de prontitud -------------------------------------------------

function ChecklistCard({ filing }: { filing: FilingSummary }) {
  const checklist = filing.checklist;
  const done = checklist.filter((item) => item.done).length;
  return (
    <Card className="p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <Label>入力状況 · Estado de los datos</Label>
        <span className="tabular text-xs font-medium text-[var(--color-sumi-soft)]">
          {done}/{checklist.length}
        </span>
      </div>
      <p className="mb-3 text-sm">Esta lista no confirma que la declaración esté completa ni presentada.</p>
      <ul className="space-y-2.5">
        {checklist.map((item) => (
          <li key={item.key} className="flex items-start gap-3">
            <span
              className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full ${
                item.done
                  ? "bg-[var(--color-seiji)] text-white"
                  : "border border-[var(--color-hairline)] text-[var(--color-sumi-soft)]"
              }`}
            >
              {item.done && <Icon name="check" className="h-3 w-3" />}
            </span>
            <div>
              <p
                className={`text-sm ${item.done ? "text-[var(--color-sumi)]" : "font-medium text-[var(--color-sumi)]"}`}
              >
                {item.label}
              </p>
              {item.detail && (
                <p className="text-xs text-[var(--color-sumi-soft)]">{item.detail}</p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// --- Descargas --------------------------------------------------------------

const PDF_FORMS: { form: FilingPdfForm; title: string; desc: string; icon: IconName }[] =
  [
    {
      form: "shinkokusho",
      title: "確定申告書 第一表・第二表",
      desc: "所得・控除・税額の本表",
      icon: "file",
    },
    {
      form: "kessansho",
      title: "青色申告決算書",
      desc: "損益計算書・貸借対照表",
      icon: "book",
    },
    {
      form: "shiwakecho",
      title: "仕訳帳",
      desc: "確認済みの取引の仕訳",
      icon: "tray",
    },
    {
      form: "motocho",
      title: "総勘定元帳",
      desc: "勘定科目ごとの元帳",
      icon: "archive",
    },
  ];

function DownloadsCard({ filing }: { filing: FilingSummary }) {
  const id = filing.draft_id;
  if (filing.year !== 2025) {
    return (
      <Card className="p-5 sm:p-6">
        <Label>申告書・帳簿のダウンロード</Label>
        <p className="mt-3 text-sm leading-relaxed text-[var(--color-sumi)]">
          {filing.year}年分の提出用PDF・e-Tax・決算書CSVは、様式の検証が完了するまで利用できません。
          令和7年の様式を代用して提出しないでください。
        </p>
        <p className="mt-2 text-sm text-[var(--color-sumi-soft)]">
          El cálculo es provisional. Los formularios y archivos para presentar de {filing.year} todavía no están verificados.
        </p>
        {filing.year === 2026 && (
          <div className="mt-4 rounded-lg border border-[var(--color-hairline)] p-4">
            <p className="text-sm font-semibold">Proyecto de formularios 令和8年分 para consulta</p>
            <p className="mt-2 text-sm">国税庁 lo identifica como proyecto (案): podría cambiar y está previsto para uso desde enero de 2027. La app todavía no rellena ni valida estos campos para presentar.</p>
            <a className="mt-3 inline-block text-sm underline" href="https://www.nta.go.jp/taxes/shiraberu/shinkoku/pdf/0026006-063.pdf" target="_blank" rel="noopener noreferrer">Abrir proyecto de 国税庁 (PDF, aproximadamente 24 MB)</a>
            <a className="mt-2 block text-sm underline" href="https://www.nta.go.jp/taxes/shiraberu/shinkoku/kakutei.htm" target="_blank" rel="noopener noreferrer">Consultar la página oficial y posibles actualizaciones</a>
          </div>
        )}
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {PDF_FORMS.filter((f) => f.form === "shiwakecho" || f.form === "motocho").map((f) => (
            <DownloadRow key={f.form} href={filingPdfUrl(id, f.form)} icon={f.icon} title={f.title} desc={f.desc} tag="PDF" />
          ))}
        </div>
      </Card>
    );
  }
  return (
    <Card className="p-5 sm:p-6">
      <Label>申告書・帳簿のダウンロード</Label>

      <div className="mt-4">
        <DownloadRow href={filingOfficialPackageUrl(id)} icon="archive" title="申告書類の下書き ZIP"
          desc="PDF・CSV・帳簿。XTX no está incluido" tag="ZIP" />
      </div>
      <p className="mt-3 text-sm">Revisa el aviso dentro del ZIP: el XTX requiere completar la identidad, los detalles y las verificaciones de presentación. Las deducciones sin categoría definida no se asignan automáticamente a su casilla. En el PDF de 青色申告決算書 las páginas 2 y 3 están en blanco; en 白色, la página 2 de la 収支内訳書 está en blanco. Complétalas cuando corresponda. La validación de formato no confirma la aceptación por e-Tax.</p>

      <div className="mt-4 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {PDF_FORMS.map((f) => (
          <DownloadRow
            key={f.form}
            href={filingPdfUrl(id, f.form)}
            icon={f.icon}
            title={f.title}
            desc={f.desc}
            tag="PDF"
          />
        ))}
      </div>

      <div className="mt-4 border-t border-[var(--color-hairline)] pt-4">
        <p className="mb-2.5 text-xs font-medium text-[var(--color-sumi-soft)]">
          e-Tax 用ファイル
        </p>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <p className="rounded-lg border border-[var(--color-hairline)] p-3 text-sm">
            XTX: completa la identidad y los detalles; revisa el XSD y los requisitos pendientes debajo.
          </p>
          <DownloadRow
            href={filingCsvUrl(id)}
            icon="box"
            title="決算書 CSV"
            desc="参考CSV（SHIFT-JIS・e-Tax未検証）"
            tag="CSV"
          />
        </div>
        <XtxReviewForm key={id} draftId={id} />
      </div>
    </Card>
  );
}

export function DownloadRow({
  href,
  icon,
  title,
  desc,
  tag,
}: {
  href: string;
  icon: IconName;
  title: string;
  desc: string;
  tag: string;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function download() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(href, { cache: "no-store" });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: { code?: string } } | null;
        const code = body?.detail?.code;
        throw new Error(code === "official_template_missing"
          ? "Falta la plantilla oficial. No se ha generado el documento; revisa la instalación de la app."
          : code === "official_package_file_missing"
            ? "Falta un archivo necesario. No se ha generado el paquete; revisa la instalación de la app."
            : code === "xtx_incomplete_mapping"
              ? "El archivo e-Tax no admite todavía todos tus ingresos o deducciones. Usa la herramienta oficial y revisa los datos."
            : code === "tax_office_unrecognized"
              ? "La oficina fiscal no está configurada o la app no la reconoce. Revisa tu 税務署 y completa la declaración en la herramienta oficial."
            : "No se pudo descargar el documento. Revisa la conexión y vuelve a intentarlo.");
      }
      const type = response.headers.get("content-type") ?? "";
      if (type.includes("text/html") || type.includes("application/json")) {
        throw new Error("La respuesta no es un documento descargable. Revisa tu sesión y vuelve a intentarlo.");
      }
      const disposition = response.headers.get("content-disposition") ?? "";
      const filename = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? `documento.${tag.toLowerCase().replace(/^\./, "")}`;
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch (failure) {
      setError(failure instanceof Error && !(failure instanceof TypeError)
        ? failure.message : "No se pudo descargar el documento. Revisa la conexión y vuelve a intentarlo.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
    <button type="button" onClick={() => void download()} disabled={busy}
      className="group flex w-full items-center gap-3 rounded-[var(--radius-card)] border border-[var(--color-hairline)] p-3 text-left transition-shadow hover:shadow-[var(--shadow-lift)] disabled:opacity-50">
      <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
        <Icon name={icon} className="h-5 w-5" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-[var(--color-sumi)]">
          {busy ? "Descargando…" : title}
        </p>
        <p className="truncate text-xs text-[var(--color-sumi-soft)]">{desc}</p>
      </div>
      <span className="shrink-0 rounded-[var(--radius-pill)] bg-[var(--color-paper-sink)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-sumi-soft)]">
        {tag}
      </span>
      <Icon
        name="upload"
        className="h-4 w-4 shrink-0 text-[var(--color-sumi-soft)] transition-colors group-hover:text-[var(--color-seiji)]"
      />
    </button>
    {error && <p role="alert" className="mt-2 text-sm">{error}</p>}
    </div>
  );
}

// --- Guia e-Tax + disclaimer ------------------------------------------------

const ETAX_STEPS = [
  "XTXは本人情報・明細・公式XSD・提出内容の検証が完了するまでダウンロードできません。",
  "国税庁の確定申告書等作成コーナーで内容を入力し、確認してください。",
  "提出方法や必要な書類は国税庁または税務署にご確認ください。",
];

function EtaxGuideCard() {
  return (
    <Card className="p-5 sm:p-6">
      <Label>e-Tax での提出方法</Label>
      <ol className="mt-4 space-y-3">
        {ETAX_STEPS.map((step, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[var(--color-sumi)] text-[11px] font-bold text-white">
              {i + 1}
            </span>
            <p className="text-sm leading-relaxed text-[var(--color-sumi)]">{step}</p>
          </li>
        ))}
      </ol>

      <div className="mt-5 flex items-start gap-2.5 rounded-[var(--radius-card)] bg-[var(--color-paper-sink)] p-3.5">
        <Icon
          name="shield"
          className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-sumi-soft)]"
        />
        <p className="text-xs leading-relaxed text-[var(--color-sumi-soft)]">
          このアプリは申告を支援するツールです（税務代理ではありません）。直接 e-Tax へ送信する機能はありません。
          生成した書類は、提出前に必ず内容をご確認ください。不明な点は税理士・税務署にご相談ください。
        </p>
      </div>
    </Card>
  );
}

// --- Skeleton ---------------------------------------------------------------

function FilingSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-64 w-full" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}
