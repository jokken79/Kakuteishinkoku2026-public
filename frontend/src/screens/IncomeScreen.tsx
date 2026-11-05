/**
 * 収入 (Ingresos) — entrada editable de los ingresos reales del owner.
 *
 * Antes el 売上 (¥6,800,000) y el 源泉徴収 (¥410,000) estaban HARDCODEADOS en el
 * backend (demo). Esta pantalla los saca de ahi: el owner ingresa SUS ingresos
 * (売上 del 事業, 給与 + 源泉徴収, 雑所得, 不動産) y la declaracion sale con sus
 * datos. Al editar un ingreso, el 事業所得 y el 納付額 del header se recalculan en
 * vivo (mismo motor `/filing/draft` que el dashboard y el 確定申告).
 *
 * Flujo: 収入 → 仕訳(経費) → 控除 → 確定申告. Aca el owner fija el ingreso bruto; los
 * 経費 vienen de los 仕訳 confirmados; las 控除 del wizard.
 */
import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  useCreateIncomeSource,
  useActiveYearLock,
  useDeleteIncomeSource,
  useFilingDraft,
  useIncomeSources,
  usePatchIncomeSource,
} from "../lib/hooks";
import type { IncomeSource, IncomeType } from "../lib/api";
import {
  INCOME_ES_LABEL,
  INCOME_KINDS,
  type IncomeKindDef,
} from "../lib/incomeCatalog";
import { formatAmount, formatYen } from "../lib/format";
import { Card, EmptyState, ErrorState, Label, Skeleton } from "../components/ui";
import { Icon } from "../components/Icon";
import { HelpSubtitle, HelpTerm } from "../components/HelpTerm";
import { useUiStore } from "../lib/store";
import { screenVariants } from "../variants/layoutVariants";
import { stepBodyVariants, taxPulseVariants } from "../variants/deductionVariants";

export function IncomeScreen() {
  const { data: list, isLoading, isError, refetch } = useIncomeSources();
  const { isReadOnly, label: lockLabel } = useActiveYearLock();
  // Mismo motor que el dashboard y el 確定申告: el 事業所得/納付額 del header
  // coincide exactamente con el del 確定申告 y se recalcula al editar un ingreso.
  const { data: tax } = useFilingDraft();

  // Tarjeta abierta del acordeon (una a la vez, conversacional).
  const [openType, setOpenType] = useState<string | null>("new:jigyo");

  const sources = useMemo(() => list?.income_sources ?? [], [list]);
  const byType = useMemo(() => {
    const map: Partial<Record<IncomeType, IncomeSource[]>> = {};
    for (const s of sources) (map[s.income_type] ??= []).push(s);
    return map;
  }, [sources]);

  // Tipos nucleo (siempre visibles) + opcionales que YA estan registrados.
  const visibleKinds = INCOME_KINDS.filter((k) => k.core || byType[k.type] || openType === `new:${k.type}`);
  const addableKinds = INCOME_KINDS.filter((k) => !k.core && !byType[k.type]);

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-2xl px-4 py-6 pb-24 sm:px-8 sm:py-10"
    >
      {/* Header con 事業所得 + 納付額 EN VIVO */}
      <IncomeHeader
        businessIncome={tax?.business_income}
        salesRevenue={list?.sales_revenue}
        finalAmount={tax?.final_amount}
        isRefund={tax?.is_refund ?? false}
        withholding={list?.total_withholding}
      />
      {isReadOnly && (
        <Card className="mt-5 border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] p-4">
          <p className="text-sm font-medium text-[var(--color-sumi)]">
            {lockLabel}の年度は読み取り専用です。収入の登録・更新・削除はできません。
          </p>
        </Card>
      )}

      {/* Tarjetas de ingreso por tipo */}
      <section className="mt-8">
        <div className="mb-3 flex items-center gap-2">
          <Icon name="signal" className="h-4 w-4 text-[var(--color-sumi-soft)]" />
          <Label>あなたの収入を入力</Label>
        </div>

        {isLoading ? (
          <div className="space-y-3">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : isError ? (
          <Card>
            <ErrorState
              message="収入データの読み込みに失敗しました。バックエンドの接続をご確認ください。"
              onRetry={() => void refetch()}
            />
          </Card>
        ) : (
          <div className="space-y-3">
            {visibleKinds.map((kind) => {
              const entries = byType[kind.type] ?? [];
              const newKey = `new:${kind.type}`;
              return <div key={kind.type} className="space-y-2">
                {entries.map((entry) => <IncomeCard key={entry.id} kind={kind} existing={entry}
                  open={openType === entry.id} readOnly={isReadOnly}
                  onToggle={() => setOpenType((prev) => prev === entry.id ? null : entry.id)} />)}
                {(entries.length === 0 || openType === newKey) && <IncomeCard key={newKey}
                  kind={kind} existing={undefined} open={openType === newKey} readOnly={isReadOnly}
                  onCreated={(id) => setOpenType(id)}
                  onToggle={() => setOpenType((prev) => prev === newKey ? null : newKey)} />}
                {entries.length > 0 && openType !== newKey && <button type="button"
                  disabled={isReadOnly} onClick={() => setOpenType(newKey)}
                  className="rounded-lg border border-[var(--color-hairline)] px-3 py-2 text-sm disabled:opacity-50">
                  Añadir otra fuente: {kind.label}
                </button>}
              </div>;
            })}
          </div>
        )}

        {/* Agregar tipos opcionales (雑所得 / 不動産) */}
        {!isLoading && !isError && addableKinds.length > 0 && (
          <div className="mt-5">
            <p className="mb-2 text-xs font-medium text-[var(--color-sumi-soft)]">
              他の収入を追加
            </p>
            <div className="flex flex-wrap gap-2">
              {addableKinds.map((kind) => (
                <button
                  key={kind.type}
                  type="button"
                  onClick={() => setOpenType(`new:${kind.type}`)}
                  disabled={isReadOnly}
                  className="flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-dashed border-[var(--color-hairline)] px-3.5 py-2 text-sm font-medium text-[var(--color-sumi-soft)] transition-colors hover:border-[var(--color-seiji)] hover:text-[var(--color-seiji)]"
                >
                  <Icon name={kind.icon} className="h-4 w-4" />＋ {kind.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Resumen de ingresos registrados */}
      <RegisteredIncomeSummary
        sources={sources}
        salesRevenue={list?.sales_revenue ?? 0}
        withholding={list?.total_withholding ?? 0}
      />
    </motion.div>
  );
}

// --- Header ----------------------------------------------------------------

function IncomeHeader({
  businessIncome,
  salesRevenue,
  finalAmount,
  isRefund,
  withholding,
}: {
  businessIncome: number | undefined;
  salesRevenue: number | undefined;
  finalAmount: number | undefined;
  isRefund: boolean;
  withholding: number | undefined;
}) {
  return (
    <section className="rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] p-5 shadow-[var(--shadow-paper)] sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>現在の事業所得</Label>
          <HelpSubtitle term="事業所得" className="mt-0.5" />
          <motion.p
            variants={taxPulseVariants}
            animate={businessIncome === undefined ? "idle" : "pulse"}
            key={businessIncome}
            className="mt-1 flex items-baseline gap-1"
          >
            <span className="tabular text-2xl font-medium text-[var(--color-sumi)]">
              ¥
            </span>
            <span className="tabular text-4xl font-bold tracking-tight text-[var(--color-sumi)] sm:text-5xl">
              {businessIncome === undefined ? "—" : formatAmount(businessIncome)}
            </span>
          </motion.p>
        </div>

        {/* 予想納税額 / 還付見込み (mismo numero que el 確定申告) */}
        <div
          className={`rounded-[var(--radius-card)] px-4 py-3 text-right ${isRefund ? "bg-[var(--color-seiji-soft)]" : "bg-[var(--color-paper-sink)]"}`}
        >
          <p
            className={`text-[11px] font-medium uppercase tracking-[0.12em] ${isRefund ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi-soft)]"}`}
          >
            {isRefund ? "還付見込み" : "予想納税額"}
          </p>
          <p
            className={`tabular mt-0.5 text-2xl font-bold ${isRefund ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]"}`}
          >
            {finalAmount === undefined ? "—" : formatYen(finalAmount)}
          </p>
        </div>
      </div>
      <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm leading-relaxed text-[var(--color-sumi-soft)]">
        <span className="inline-flex items-center">
          売上<HelpTerm term="売上" />：
          <span className="tabular ml-1 font-medium text-[var(--color-sumi)]">
            {salesRevenue === undefined ? "—" : formatYen(salesRevenue)}
          </span>
        </span>
        <span className="inline-flex items-center">
          源泉徴収<HelpTerm term="源泉徴収" />：
          <span className="tabular ml-1 font-medium text-[var(--color-sumi)]">
            {withholding === undefined ? "—" : formatYen(withholding)}
          </span>
        </span>
      </p>
    </section>
  );
}

// --- Tarjeta de un tipo de ingreso ----------------------------------------

function IncomeCard({
  kind,
  existing,
  open,
  readOnly,
  onCreated,
  onToggle,
}: {
  kind: IncomeKindDef;
  existing: IncomeSource | undefined;
  open: boolean;
  readOnly: boolean;
  onCreated?: (id: string) => void;
  onToggle: () => void;
}) {
  const create = useCreateIncomeSource();
  const patch = usePatchIncomeSource();
  const remove = useDeleteIncomeSource();

  const [gross, setGross] = useState<string>(
    existing ? String(existing.gross) : "",
  );
  const [withholding, setWithholding] = useState<string>(
    existing && existing.withholding ? String(existing.withholding) : "",
  );
  const [expenses, setExpenses] = useState<string>(
    existing && existing.expenses ? String(existing.expenses) : "",
  );
  const [label, setLabel] = useState(
    typeof existing?.meta?.label === "string" ? existing.meta.label : "",
  );

  const registered = Boolean(existing);
  const pending = create.isPending || patch.isPending || remove.isPending;

  const parsedGross = Number(gross.replaceAll(",", "")) || 0;
  const parsedWithholding = Number(withholding.replaceAll(",", "")) || 0;
  const parsedExpenses = Number(expenses.replaceAll(",", "")) || 0;

  const handleSave = () => {
    if (readOnly) return;
    const payload = {
      income_type: kind.type,
      gross: parsedGross,
      withholding: kind.hasWithholding ? parsedWithholding : 0,
      expenses: kind.hasExpenses ? parsedExpenses : 0,
      meta: { label: label.trim() },
    };
    if (existing) {
      if (!window.confirm("Se actualizará esta fuente de ingresos. Haz una copia de seguridad antes de continuar. ¿Guardar los cambios?")) return;
      patch.mutate({
        id: existing.id,
        patch: {
          gross: payload.gross,
          withholding: payload.withholding,
          expenses: payload.expenses,
          meta: payload.meta,
        },
      });
    } else {
      create.mutate(payload, { onSuccess: (created) => onCreated?.(created.id) });
    }
  };

  const handleRemove = () => {
    if (readOnly) return;
    if (existing) {
      if (!window.confirm("Se eliminará esta fuente de ingresos. Haz una copia de seguridad antes de continuar. ¿Eliminarla?")) return;
      remove.mutate(existing.id, {
        onSuccess: () => {
          setGross("");
          setWithholding("");
          setExpenses("");
        },
      });
    }
  };

  // Etiqueta del estado en la cabecera.
  const summaryText = registered
    ? kind.hasWithholding && existing && existing.withholding > 0
      ? `${formatYen(existing?.gross)}・源泉 ${formatYen(existing?.withholding)}`
      : `登録済み・${formatYen(existing?.gross)}`
    : kind.question;

  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-[var(--color-paper-sink)]"
      >
        <span
          className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${registered ? "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]" : "bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]"}`}
        >
          <Icon name={registered ? "check" : kind.icon} className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-[var(--color-sumi)]">
            {kind.label}
          </span>
          <HelpSubtitle className="truncate">
            {INCOME_ES_LABEL[kind.type]}
          </HelpSubtitle>
          <span className="block truncate text-xs text-[var(--color-sumi-soft)]">
            {typeof existing?.meta?.label === "string" && existing.meta.label ? `${existing.meta.label}・` : ""}{summaryText}
          </span>
        </span>
        <Icon
          name="arrow"
          className={`h-4 w-4 shrink-0 text-[var(--color-sumi-soft)] transition-transform ${open ? "rotate-90" : ""}`}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            variants={stepBodyVariants}
            initial="collapsed"
            animate="expanded"
            exit="collapsed"
            className="overflow-hidden"
          >
            <div className="border-t border-[var(--color-hairline)] px-4 py-4">
              <p className="flex items-start text-sm leading-relaxed text-[var(--color-sumi)]">
                <span>{kind.question}</span>
                <HelpTerm term={kind.term} size="md" />
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-[var(--color-sumi-soft)]">
                {kind.help}
              </p>
              {kind.type === "fudosan" && <p className="mt-2 text-sm">
                Si hay pérdida inmobiliaria, la simulación no separa las excepciones de 損益通算, como ciertos intereses de préstamos para terrenos. Revisa el cálculo antes de declarar.
              </p>}
              {kind.type === "zatsu" && <p className="mt-2 text-sm">
                El cálculo trata cada fuente por separado y no cubre todas las reglas entre subcategorías de 雑所得. Si unas fuentes tienen pérdidas y otras beneficios, revisa el total antes de declarar.
              </p>}

              <div className="mt-4 space-y-3">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-[var(--color-sumi-soft)]">会社名・収入の名前（任意） / Empresa o fuente (opcional)</span>
                  <input type="text" maxLength={80} value={label} disabled={readOnly}
                    onChange={(event) => setLabel(event.target.value)}
                    className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2.5 text-sm text-[var(--color-sumi)]" />
                </label>
                <AmountField
                  id={`gross-${existing?.id ?? `new-${kind.type}`}`}
                  label={kind.grossLabel}
                  placeholder={kind.placeholder}
                  value={gross}
                  onChange={setGross}
                  disabled={readOnly}
                />
                {kind.hasWithholding && (
                  <AmountField
                    id={`wh-${existing?.id ?? `new-${kind.type}`}`}
                    label="源泉徴収税額（源泉徴収票から）"
                    placeholder="例：410,000"
                    value={withholding}
                    onChange={setWithholding}
                    disabled={readOnly}
                  />
                )}
                {kind.hasExpenses && (
                  <AmountField
                    id={`exp-${existing?.id ?? `new-${kind.type}`}`}
                    label="必要経費（あれば）"
                    placeholder="例：0"
                    value={expenses}
                    onChange={setExpenses}
                    disabled={readOnly}
                  />
                )}
              </div>

              <div className="mt-4 flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={readOnly || pending}
                  className="flex items-center gap-1.5 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  <Icon name="check" className="h-4 w-4" />
                  {pending ? "保存中…" : registered ? "更新する" : "この収入を登録"}
                </button>
                {registered && (
                  <button
                    type="button"
                    onClick={handleRemove}
                    disabled={readOnly || pending}
                    className="rounded-[var(--radius-pill)] px-3 py-2.5 text-sm font-medium text-[var(--color-sumi-soft)] transition-colors hover:text-[var(--color-shuiro)]"
                  >
                    削除
                  </button>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}

function AmountField({
  id,
  label,
  placeholder,
  value,
  onChange,
  disabled = false,
}: {
  id: string;
  label: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <label htmlFor={id} className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--color-sumi-soft)]">
        {label}
      </span>
      <div className="flex items-center rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] pl-3.5 pr-3 focus-within:border-[var(--color-seiji)]">
        <span className="tabular mr-0.5 text-sm text-[var(--color-sumi-soft)]">¥</span>
        <input
          id={id}
          type="text"
          inputMode="numeric"
          placeholder={placeholder}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value.replace(/[^0-9,]/g, ""))}
          className="tabular w-full bg-transparent px-2 py-2.5 text-right text-sm text-[var(--color-sumi)] outline-none placeholder:text-[var(--color-sumi-soft)]/50"
        />
      </div>
    </label>
  );
}

// --- Resumen de ingresos registrados ---------------------------------------

function RegisteredIncomeSummary({
  sources,
  salesRevenue,
  withholding,
}: {
  sources: IncomeSource[];
  salesRevenue: number;
  withholding: number;
}) {
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  const withValue = sources.filter((s) => s.gross > 0 || s.withholding > 0);

  return (
    <section className="mt-8">
      <div className="mb-3 flex items-center gap-2">
        <Icon name="archive" className="h-4 w-4 text-[var(--color-sumi-soft)]" />
        <Label>登録済みの収入</Label>
      </div>
      <Card className="p-5">
        {withValue.length === 0 ? (
          <EmptyState
            icon="signal"
            title="売上を入力してください"
            hint="上のカードで事業の売上や給与を入力すると、ここに集まります。経費は仕訳トレイから自動で差し引かれ、納税額に反映されます。"
          />
        ) : (
          <>
            <ul className="divide-y divide-[var(--color-hairline)]">
              {withValue.map((s) => (
                <li
                  key={s.id}
                  className="flex items-center justify-between py-3"
                >
                  <span className="flex items-center gap-2.5">
                    <span className="text-sm text-[var(--color-sumi)]">
                      {labelFor(s.income_type)}
                      {typeof s.meta?.label === "string" && s.meta.label ? `・${s.meta.label}` : ""}
                    </span>
                    {s.withholding > 0 && (
                      <span className="tabular rounded-[var(--radius-pill)] bg-[var(--color-paper-sink)] px-2 py-0.5 text-[11px] text-[var(--color-sumi-soft)]">
                        源泉 {formatYen(s.withholding)}
                      </span>
                    )}
                  </span>
                  <span className="tabular text-sm font-medium text-[var(--color-sumi)]">
                    {formatYen(s.gross)}
                  </span>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex items-center justify-between border-t border-[var(--color-hairline)] pt-3">
              <span className="text-sm font-semibold text-[var(--color-sumi)]">
                売上合計
              </span>
              <span className="tabular text-base font-bold text-[var(--color-sumi)]">
                {formatYen(salesRevenue)}
              </span>
            </div>
            <p className="mt-2 flex items-center justify-between text-xs text-[var(--color-sumi-soft)]">
              <span>源泉徴収の合計</span>
              <span className="tabular font-medium text-[var(--color-seiji)]">
                {formatYen(withholding)}
              </span>
            </p>
          </>
        )}
      </Card>

      {/* Guia del flujo: 収入 → 仕訳(経費) → 控除 → 確定申告 */}
      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-[var(--color-sumi-soft)]">
        <span>次のステップ：</span>
        <button
          type="button"
          onClick={() => setActiveSection("journal-tray")}
          className="inline-flex items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3 py-1.5 font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
        >
          経費を確認（仕訳）
          <Icon name="arrow" className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => setActiveSection("deduction-wizard")}
          className="inline-flex items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3 py-1.5 font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
        >
          控除を登録
          <Icon name="arrow" className="h-3.5 w-3.5" />
        </button>
      </div>
    </section>
  );
}

/** Etiqueta japonesa corta de un tipo de ingreso para el resumen. */
function labelFor(type: IncomeType): string {
  const map: Record<IncomeType, string> = {
    jigyo: "事業収入（売上）",
    kyuyo: "給与収入",
    zatsu: "雑所得",
    fudosan: "不動産所得",
  };
  return map[type] ?? type;
}
