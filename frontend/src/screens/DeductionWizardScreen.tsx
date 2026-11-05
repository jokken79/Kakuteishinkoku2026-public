/**
 * 控除ウィザード (Fase 3B-1) — "質問に答えるだけ".
 *
 * Flujo conversacional: el header muestra el impuesto estimado EN VIVO y el
 * 節税額 total (seiji). Arriba, un panel de sugerencias proactivas ("見逃している
 * 控除"). El cuerpo es un acordeon de categorias (una pregunta por paso) con
 * ayuda contextual (que 控除証明書 hace falta). Al guardar una deduccion, el
 * impuesto del header BAJA y aparece el 節税額 del paso. Abajo, el resumen
 * editable/borrable cuadra con la tarjeta 控除適用済み del dashboard.
 */
import { useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  useCreateDeduction,
  useActiveYearLock,
  useDeductions,
  useDeductionSuggestions,
  useDeductionSummary,
  useDeleteDeduction,
  useFilingDraft,
  usePatchDeduction,
} from "../lib/hooks";
import type { Deduction, DeductionSuggestion, DeductionType } from "../lib/api";
import {
  DEDUCTION_STEPS,
  DEDUCTION_LABELS,
  STEP_BY_TYPE,
  type DeductionStep,
} from "../lib/deductionCatalog";
import { formatAmount, formatYen } from "../lib/format";
import { Card, EmptyState, ErrorState, Label, Skeleton } from "../components/ui";
import { Icon } from "../components/Icon";
import { HelpSubtitle, HelpTerm } from "../components/HelpTerm";
import { DependentsManager } from "../components/DependentsManager";
import { KoujoXmlImport } from "../components/KoujoXmlImport";
import { screenVariants, staggerContainer } from "../variants/layoutVariants";
import {
  savingBadgeVariants,
  stepBodyVariants,
  suggestionVariants,
  taxPulseVariants,
} from "../variants/deductionVariants";

export function DeductionWizardScreen() {
  const { isReadOnly, label: lockLabel } = useActiveYearLock();
  const { data: list, isLoading, isError, refetch } = useDeductions();
  const { data: summary } = useDeductionSummary();
  const { data: suggestions } = useDeductionSuggestions();
  // Mismo motor que el dashboard y el filing (`/filing/draft`): el 予想納税額 del
  // header del wizard coincide exactamente con el 納付額 del 確定申告.
  const { data: tax } = useFilingDraft();

  // Paso abierto del acordeon (uno a la vez = un paso a la vez, conversacional).
  const [openType, setOpenType] = useState<DeductionType | null>(null);
  // Para resaltar el paso al que se llega desde una sugerencia.
  const stepRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const deductions = useMemo(() => list?.deductions ?? [], [list]);
  const byType = useMemo(() => {
    const map: Partial<Record<DeductionType, Deduction>> = {};
    for (const d of deductions) map[d.type] = d;
    return map;
  }, [deductions]);

  const totalSaving = summary?.total_saving ?? 0;
  const appliedTotal = summary?.applied_total ?? list?.applied_total ?? 0;
  const isRefund = tax?.is_refund ?? false;

  const openStep = (type: DeductionType) => {
    setOpenType(type);
    // Desplaza el paso a la vista (sugerencia -> paso del wizard).
    requestAnimationFrame(() => {
      stepRefs.current[type]?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  };

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-2xl px-4 py-6 pb-24 sm:px-8 sm:py-10"
    >
      {/* Header con impuesto EN VIVO + 節税額 total */}
      <WizardHeader
        finalAmount={tax?.final_amount}
        isRefund={isRefund}
        totalSaving={totalSaving}
      />
      {isReadOnly && (
        <Card className="mt-5 border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] p-4">
          <p className="text-sm font-medium text-[var(--color-sumi)]">
            {lockLabel}の年度は読み取り専用です。控除の登録・更新・削除はできません。
          </p>
        </Card>
      )}

      {/* Sugerencias proactivas */}
      <SuggestionPanel suggestions={suggestions} byType={byType} onOpen={openStep} />

      {/* Wizard: acordeon de categorias */}
      <section className="mt-8">
        <div className="mb-3 flex items-center gap-2">
          <Icon name="compass" className="h-4 w-4 text-[var(--color-sumi-soft)]" />
          <Label>質問に答えて控除を登録</Label>
        </div>

        {isLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : isError ? (
          <Card>
            <ErrorState
              message="控除データの読み込みに失敗しました。バックエンドの接続をご確認ください。"
              onRetry={() => void refetch()}
            />
          </Card>
        ) : (
          <div className="space-y-3">
            {/* El 扶養控除 (fuyo) se gestiona en su propia sección estructurada
                (DependentsManager): familiares con edad/居住地/国外 docs. */}
            {DEDUCTION_STEPS.filter((s) => s.type !== "fuyo").map((step) => (
              <div
                key={step.type}
                ref={(el) => {
                  stepRefs.current[step.type] = el;
                }}
              >
                <WizardStep
                  step={step}
                  existing={byType[step.type]}
                  open={openType === step.type}
                  readOnly={isReadOnly}
                  onToggle={() =>
                    setOpenType((prev) => (prev === step.type ? null : step.type))
                  }
                />
              </div>
            ))}
          </div>
        )}
      </section>

      <DisabilitySelfSection
        existing={byType.disability_self}
        hasOther={deductions.some((deduction) => deduction.type === "other")}
        readOnly={isReadOnly}
      />

      {/* 控除証明書（XML）取り込み — Nivel 2 e-Tax */}
      <KoujoXmlImport readOnly={isReadOnly} />

      {/* 扶養家族 (扶養控除 detallado + 国外居住) — research 08 */}
      <DependentsManager readOnly={isReadOnly} />

      {/* Resumen de deducciones registradas */}
      <RegisteredSummary deductions={deductions} appliedTotal={appliedTotal} />
    </motion.div>
  );
}

function DisabilitySelfSection({
  existing,
  hasOther,
  readOnly,
}: {
  existing: Deduction | undefined;
  hasOther: boolean;
  readOnly: boolean;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const create = useCreateDeduction();
  const remove = useDeleteDeduction();
  const pending = create.isPending || remove.isPending;

  function addDeduction() {
    if (readOnly || existing || !confirmed || pending) return;
    create.mutate({ type: "disability_self", amount: 270_000 });
  }

  function removeDeduction() {
    if (readOnly || !existing || pending) return;
    if (!window.confirm("Se eliminará esta deducción del año. Guarda una copia de tus datos antes de continuar. ¿Eliminarla?")) return;
    remove.mutate(existing.id);
  }

  return (
    <section className="mt-8">
      <Label>障害者控除 · Discapacidad</Label>
      <Card className="mt-3 space-y-3 p-5">
        <p className="font-semibold">一般障害者（本人）</p>
        <p className="text-sm">Para el titular con categoría ordinaria, por ejemplo 精神障害者保健福祉手帳 de 2級 o 3級 vigente. Reduce la base del 所得税 en ¥270.000 y la del 住民税 en ¥260.000; no es una devolución directa.</p>
        <p className="text-sm">Revisa la vigencia del 手帳, que corresponda al año seleccionado y que la deducción no esté incluida ya en その他の控除.</p>
        {hasOther && <p role="alert" className="text-sm font-semibold">Hay una deducción その他 registrada. Revisa su contenido para evitar duplicar la discapacidad; la app no puede clasificarla automáticamente.</p>}
        {existing ? (
          <div className="flex flex-wrap items-center gap-3">
            <p role="status">登録済み · Registrada para este año</p>
            <button type="button" disabled={readOnly || pending} onClick={removeDeduction} className="rounded-lg border border-[var(--color-hairline)] px-4 py-2 disabled:opacity-50">Eliminar deducción</button>
          </div>
        ) : (
          <>
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} disabled={readOnly} onChange={(event) => setConfirmed(event.target.checked)} />He comprobado que cumplo las condiciones y que no está registrada dos veces.</label>
            <button type="button" disabled={readOnly || pending || !confirmed} onClick={addDeduction} className="rounded-lg bg-[var(--color-seiji)] px-4 py-2 font-semibold text-white disabled:opacity-50">Registrar ¥270.000</button>
          </>
        )}
        {(create.isError || remove.isError) && <p role="alert">No se pudo actualizar la deducción. Comprueba la conexión y el año seleccionado.</p>}
      </Card>
    </section>
  );
}

// --- Header ----------------------------------------------------------------

function WizardHeader({
  finalAmount,
  isRefund,
  totalSaving,
}: {
  finalAmount: number | undefined;
  isRefund: boolean;
  totalSaving: number;
}) {
  // Pulso cuando el impuesto cambia (feedback "bajó").
  const prev = useRef<number | undefined>(undefined);
  const pulse = finalAmount !== undefined && prev.current !== undefined && finalAmount !== prev.current;
  if (finalAmount !== undefined) prev.current = finalAmount;

  return (
    <section className="rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] p-5 shadow-[var(--shadow-paper)] sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>{isRefund ? "現在の還付見込み" : "現在の予想納税額"}</Label>
          <motion.p
            variants={taxPulseVariants}
            animate={pulse ? "pulse" : "idle"}
            className="mt-1 flex items-baseline gap-1"
          >
            <span
              className={`tabular text-2xl font-medium ${isRefund ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]"}`}
            >
              ¥
            </span>
            <span
              className={`tabular text-4xl font-bold tracking-tight sm:text-5xl ${isRefund ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]"}`}
            >
              {finalAmount === undefined ? "—" : formatAmount(finalAmount)}
            </span>
          </motion.p>
        </div>

        {/* 節税額 total (lo más satisfactorio: ver cuánto se ahorró) */}
        <div className="rounded-[var(--radius-card)] bg-[var(--color-seiji-soft)] px-4 py-3 text-right">
          <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--color-seiji)]">
            これまでの節税額
          </p>
          <p className="tabular mt-0.5 text-2xl font-bold text-[var(--color-seiji)]">
            {formatYen(totalSaving)}
          </p>
        </div>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-[var(--color-sumi-soft)]">
        控除<HelpTerm term="控除" />を登録するほど、上の金額は下がります。質問に答えるだけで大丈夫です。
      </p>
    </section>
  );
}

// --- Sugerencias proactivas ------------------------------------------------

function SuggestionPanel({
  suggestions,
  byType,
  onOpen,
}: {
  suggestions: DeductionSuggestion[] | undefined;
  byType: Partial<Record<DeductionType, Deduction>>;
  onOpen: (type: DeductionType) => void;
}) {
  // Oculta las que ya están registradas (por si la lista llega antes de refetch).
  const visible = (suggestions ?? []).filter((s) => !byType[s.type]);
  if (visible.length === 0) return null;

  return (
    <section className="mt-6">
      <div className="mb-3 flex items-center gap-2">
        <Icon name="sparkle" className="h-4 w-4 text-[var(--color-kohaku)]" />
        <Label>見逃している控除</Label>
      </div>
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-1 gap-3 sm:grid-cols-2"
      >
        {visible.map((s) => (
          <motion.button
            key={s.type}
            type="button"
            variants={suggestionVariants}
            onClick={() => onOpen(s.type)}
            className="flex h-full flex-col rounded-[var(--radius-card)] border border-[var(--color-kohaku-soft)] bg-[var(--color-kohaku-soft)] p-4 text-left transition-shadow hover:shadow-[var(--shadow-lift)]"
            aria-label={`${s.label} を登録する`}
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-semibold text-[var(--color-sumi)]">
                {s.label}
              </span>
              <Icon name="arrow" className="h-4 w-4 shrink-0 text-[var(--color-kohaku)]" />
            </div>
            <p className="mt-1.5 flex-1 text-xs leading-relaxed text-[var(--color-sumi-soft)]">
              {s.reason}
            </p>
            {s.estimated_saving != null && s.estimated_saving > 0 && (
              <p className="tabular mt-2 text-xs font-medium text-[var(--color-seiji)]">
                節税見込み 約{formatYen(s.estimated_saving)}
              </p>
            )}
          </motion.button>
        ))}
      </motion.div>
    </section>
  );
}

// --- Paso del wizard -------------------------------------------------------

function WizardStep({
  step,
  existing,
  open,
  readOnly,
  onToggle,
}: {
  step: DeductionStep;
  existing: Deduction | undefined;
  open: boolean;
  readOnly: boolean;
  onToggle: () => void;
}) {
  const create = useCreateDeduction();
  const patch = usePatchDeduction();
  const remove = useDeleteDeduction();

  const [amount, setAmount] = useState<string>(
    existing ? String(existing.amount) : "",
  );
  const reimbursementMeta = existing?.meta?.reimbursement;
  const [reimbursement, setReimbursement] = useState<string>(
    typeof reimbursementMeta === "number" ? String(reimbursementMeta) : "",
  );
  const registered = Boolean(existing);
  const pending = create.isPending || patch.isPending || remove.isPending;

  const parsedAmount = Number(amount.replaceAll(",", "")) || 0;
  const parsedReimbursement = Number(reimbursement.replaceAll(",", "")) || 0;

  const handleSave = () => {
    if (readOnly) return;
    if (parsedAmount <= 0) return;
    const meta = step.hasReimbursement
      ? { reimbursement: parsedReimbursement }
      : undefined;
    if (existing) {
      patch.mutate({ id: existing.id, patch: { amount: parsedAmount, meta } });
    } else {
      create.mutate({ type: step.type, amount: parsedAmount, meta });
    }
  };

  const handleRemove = () => {
    if (readOnly) return;
    if (existing) remove.mutate(existing.id, { onSuccess: () => setAmount("") });
  };

  return (
    <Card className="overflow-hidden">
      {/* Cabecera del paso (clickable, acordeon) */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-[var(--color-paper-sink)]"
      >
        <span
          className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${registered ? "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]" : "bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]"}`}
        >
          <Icon name={registered ? "check" : step.icon} className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-[var(--color-sumi)]">
            {step.label}
          </span>
          <HelpSubtitle term={step.label} className="truncate" />
          <span className="block truncate text-xs text-[var(--color-sumi-soft)]">
            {registered ? `登録済み・${formatYen(existing?.amount)}` : step.question}
          </span>
        </span>
        <Icon
          name="arrow"
          className={`h-4 w-4 shrink-0 text-[var(--color-sumi-soft)] transition-transform ${open ? "rotate-90" : ""}`}
        />
      </button>

      {/* Cuerpo colapsable */}
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
                <span>{step.question}</span>
                <HelpTerm term={step.label} size="md" />
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-[var(--color-sumi-soft)]">
                {step.help}
              </p>

              {/* Documento necesario */}
              <div className="mt-3 flex items-start gap-2 rounded-lg bg-[var(--color-paper-sink)] px-3 py-2">
                <Icon name="file" className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-sumi-soft)]" />
                <span className="text-xs leading-relaxed text-[var(--color-sumi-soft)]">
                  必要な書類：{step.document}
                </span>
              </div>

              {/* Inputs */}
              <div className="mt-4 space-y-3">
                <AmountField
                  id={`amount-${step.type}`}
                  label={step.amountLabel}
                  placeholder={step.placeholder}
                  value={amount}
                  onChange={setAmount}
                  disabled={readOnly}
                />
                {step.hasReimbursement && (
                  <AmountField
                    id={`reimb-${step.type}`}
                    label="保険などの補填額（あれば）"
                    placeholder="例：0"
                    value={reimbursement}
                    onChange={setReimbursement}
                    disabled={readOnly}
                  />
                )}
              </div>

              {/* Acciones */}
              <div className="mt-4 flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={readOnly || pending || parsedAmount <= 0}
                  className="flex items-center gap-1.5 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  <Icon name="check" className="h-4 w-4" />
                  {pending ? "保存中…" : registered ? "更新する" : "この控除を登録"}
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

              {/* 節税額 del paso (cuando está registrado) */}
              {registered && (
                <motion.p
                  variants={savingBadgeVariants}
                  initial="hidden"
                  animate="visible"
                  className="tabular mt-3 inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] bg-[var(--color-seiji-soft)] px-3 py-1 text-xs font-medium text-[var(--color-seiji)]"
                >
                  <Icon name="sparkle" className="h-3.5 w-3.5" />
                  控除額 {formatYen(existing?.amount)} を適用中
                </motion.p>
              )}
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

// --- Resumen de registradas ------------------------------------------------

function isRejectedDeduction(deduction: Deduction): boolean {
  return deduction.meta?.claim_status === "rejected";
}

function RegisteredSummary({
  deductions,
  appliedTotal,
}: {
  deductions: Deduction[];
  appliedTotal: number;
}) {
  const userTotal = deductions.reduce(
    (sum, deduction) => sum + (isRejectedDeduction(deduction) ? 0 : deduction.amount),
    0,
  );

  return (
    <section className="mt-8">
      <div className="mb-3 flex items-center gap-2">
        <Icon name="archive" className="h-4 w-4 text-[var(--color-sumi-soft)]" />
        <Label>登録済みの控除</Label>
      </div>
      <Card className="p-5">
        {deductions.length === 0 ? (
          <EmptyState
            icon="compass"
            title="まだ控除が登録されていません"
            hint="上の質問に答えると、ここに登録した控除が集まります。控除を入れるほど、納税額は下がります。"
          />
        ) : (
          <>
            <ul className="divide-y divide-[var(--color-hairline)]">
              {deductions.map((d) => {
                const step = STEP_BY_TYPE[d.type];
                const rejected = isRejectedDeduction(d);
                // Label japonés robusto: usa el catálogo de pasos y, para tipos
                // que no son pasos del wizard (ej. housing_loan), el mapa de
                // labels. Nunca mostramos el slug crudo (i18n).
                const label = step?.label ?? DEDUCTION_LABELS[d.type] ?? d.type;
                return (
                  <li key={d.id} className="flex items-center justify-between gap-3 py-3">
                    <span className="flex items-center gap-2.5">
                      <Icon
                        name={step?.icon ?? "check"}
                        className="h-4 w-4 text-[var(--color-sumi-soft)]"
                      />
                      <span className="text-sm text-[var(--color-sumi)]">
                        {label}
                        {rejected && (
                          <span className="ml-2 rounded-full bg-[var(--color-kohaku-soft)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-kohaku)]">
                            不承認 / No aceptado
                          </span>
                        )}
                      </span>
                    </span>
                    {rejected ? (
                      <span className="shrink-0 text-right">
                        <span className="tabular block text-sm font-semibold text-[var(--color-kohaku)]">
                          適用 {formatYen(0)}
                        </span>
                        <span className="tabular block text-[10px] text-[var(--color-sumi-soft)]">
                          申請 {formatYen(d.amount)}
                        </span>
                      </span>
                    ) : (
                      <span className="tabular shrink-0 text-sm font-medium text-[var(--color-sumi)]">
                        {formatYen(d.amount)}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
            <div className="mt-3 flex items-center justify-between border-t border-[var(--color-hairline)] pt-3">
              <span className="text-sm font-semibold text-[var(--color-sumi)]">
                控除合計（適用対象）
              </span>
              <span className="tabular text-base font-bold text-[var(--color-sumi)]">
                {formatYen(userTotal)}
              </span>
            </div>
            <p className="mt-2 flex items-center justify-between text-xs text-[var(--color-sumi-soft)]">
              <span>基礎控除を含む適用合計</span>
              <span className="tabular font-medium text-[var(--color-seiji)]">
                {formatYen(appliedTotal)}
              </span>
            </p>
          </>
        )}
      </Card>
    </section>
  );
}
