/**
 * Bandeja de 仕訳 (仕訳トレイ) — pantalla estrella. Tarjetas-documento con el
 * gesto del sello al confirmar + barra de batch ("○件をまとめて承認"). Ordena
 * por confianza (baja primero = lo que mas necesita revision).
 */
import { useMemo, useState } from "react";
import { correctReceiptRegistration, saveBusinessAllocation } from "../lib/api";
import { AnimatePresence, motion } from "framer-motion";
import {
  useBatchConfirm,
  useActiveYearLock,
  useConfirmReceipt,
  useHouseholdFromTransaction,
  usePatchReceipt,
  usePendingReceipts,
} from "../lib/hooks";
import { useUiStore } from "../lib/store";
import { confidenceLevel, formatYen } from "../lib/format";
import { Card, EmptyState, ErrorState, Skeleton } from "../components/ui";
import { Icon } from "../components/Icon";
import { HelpSubtitle, HelpTerm } from "../components/HelpTerm";
import { ReceiptCard } from "../components/ReceiptCard";
import { MixedExpenseCalculator } from "../components/MixedExpenseCalculator";
import { ManualBusinessExpense } from "../components/ManualBusinessExpense";
import { screenVariants } from "../variants/layoutVariants";
import { cardExitTransition } from "../variants/hankoVariants";

export function JournalTrayScreen() {
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  const { fiscalYear, isReadOnly, label: lockLabel } = useActiveYearLock();
  const { data: receipts, isLoading, isError, refetch } = usePendingReceipts();
  const confirmOne = useConfirmReceipt();
  const batch = useBatchConfirm();
  const patchReceipt = usePatchReceipt();
  const moveToHousehold = useHouseholdFromTransaction();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [allocationSaving, setAllocationSaving] = useState(false);
  const [accountSaving, setAccountSaving] = useState(false);
  const [registrationSaving, setRegistrationSaving] = useState(false);

  const items = useMemo(() => receipts ?? [], [receipts]);

  // Ordena: baja confianza primero (lo que mas necesita revision).
  const sorted = useMemo(
    () => [...items].sort((a, b) => (a.confidence ?? 0) - (b.confidence ?? 0)),
    [items],
  );

  const highConfidenceIds = useMemo(
    () =>
      items
        .filter((t) => t.id && confidenceLevel(t.confidence) === "high")
        .map((t) => t.id as string),
    [items],
  );

  const toggleSelect = (id: string) => {
    if (isReadOnly) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllHigh = () => {
    if (isReadOnly) return;
    setSelected(new Set(highConfidenceIds));
  };
  const clearSelection = () => setSelected(new Set());

  const selectedTotal = items
    .filter((t) => t.id && selected.has(t.id))
    .reduce((sum, t) => sum + (t.total_amount ?? 0), 0);

  const handleBatch = () => {
    const ids = [...selected];
    if (ids.length === 0 || isReadOnly || allocationSaving || accountSaving || registrationSaving) return;
    if (!window.confirm(`Se confirmarán ${ids.length} comprobantes. Los que no tengan reparto guardado se incluirán íntegros como gastos profesionales. Revisa cada uno y haz una copia de seguridad antes de continuar. ¿Confirmar?`)) return;
    batch.mutate(ids, { onSuccess: () => clearSelection() });
  };

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-2xl px-4 py-6 sm:px-8 sm:py-10"
    >
      <div className="mb-5 flex items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center text-xl font-bold text-[var(--color-sumi)]">
            仕訳トレイ
            <HelpTerm term="仕訳" size="md" />
          </h2>
          <HelpSubtitle>Asientos por revisar y aprobar</HelpSubtitle>
          <p className="mt-1 text-sm text-[var(--color-sumi-soft)]">
            確認すると朱色の印が押されます。赤はあなたの承認です。
          </p>
        </div>
        {highConfidenceIds.length > 0 && (
          <button
            type="button"
            onClick={selectAllHigh}
            disabled={isReadOnly}
            className="shrink-0 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3 py-1.5 text-xs font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
          >
            高信頼を全選択（{highConfidenceIds.length}）
          </button>
        )}
      </div>

      <Card className="mb-4 p-4">
        <p className="text-sm"><strong>Gastos mixtos:</strong> si confirmas sin guardar un reparto, se suma el importe íntegro. El OCR no comprueba qué parte corresponde al 副業. Revisa el uso profesional antes de confirmar.</p>
      </Card>
      <ManualBusinessExpense fiscalYear={fiscalYear} onSaved={() => void refetch()} />
      <MixedExpenseCalculator />

      {isReadOnly && (
        <Card className="mb-4 border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] p-4">
          <p className="text-sm font-medium text-[var(--color-sumi)]">
            {lockLabel}の年度は読み取り専用です。仕訳の承認・編集はできません。
          </p>
        </Card>
      )}

      {/* Contenido */}
      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-36 w-full" />
          ))}
        </div>
      ) : isError ? (
        <Card>
          <ErrorState
            message="仕訳の読み込みに失敗しました。バックエンドの接続をご確認ください。"
            onRetry={() => void refetch()}
          />
        </Card>
      ) : sorted.length === 0 ? (
        <Card>
          <EmptyState
            icon="check"
            title="すべて確認済みです"
            hint="未確認の仕訳はありません。新しいレシートを撮影すると、ここに提案が表示されます。"
            action={
              <button
                type="button"
                onClick={() => setActiveSection("capture")}
                className="flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white"
              >
                <Icon name="camera" className="h-4 w-4" />
                レシートを撮影
              </button>
            }
          />
        </Card>
      ) : (
        <div className="space-y-3 pb-28">
          <AnimatePresence mode="popLayout">
            {sorted.map((tx) => (
              <motion.div
                key={tx.id}
                layout
                exit={{ opacity: 0, x: 40, transition: cardExitTransition }}
              >
                <ReceiptCard
                  tx={tx}
                  selected={Boolean(tx.id && selected.has(tx.id))}
                  onToggleSelect={toggleSelect}
                  onAllocation={async (id, payload) => {
                    setAllocationSaving(true);
                    try {
                      await saveBusinessAllocation(id, payload);
                      await refetch();
                    } finally {
                      setAllocationSaving(false);
                    }
                  }}
                  onConfirm={async (id) => {
                    if (isReadOnly) return;
                    await confirmOne.mutateAsync({ id });
                  }}
                  onAccountChange={async (id, accountCode) => {
                    setAccountSaving(true);
                    try {
                      await patchReceipt.mutateAsync({ id, patch: { account_code: accountCode } });
                    } finally {
                      setAccountSaving(false);
                    }
                  }}
                  onRegistrationChange={async (id, expected, number) => {
                    setRegistrationSaving(true);
                    try {
                      await correctReceiptRegistration(id, expected, number);
                      await refetch();
                    } finally {
                      setRegistrationSaving(false);
                    }
                  }}
                  onMoveToHousehold={(id) =>
                    moveToHousehold.mutate({
                      transactionId: id,
                      // Entra al 家計簿 como "その他"; el usuario lo recategoriza ahí.
                      category: "sonota",
                    })
                  }
                  disabled={isReadOnly || allocationSaving || accountSaving || registrationSaving}
                />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}

      {/* Barra de batch (aparece cuando hay seleccion) */}
      <AnimatePresence>
        {selected.size > 0 && (
          <motion.div
            initial={{ y: 80, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
            /* Movil: elevada sobre la bottom-nav (58px) + safe-area + holgura
               (no se rozan). Desktop: pegada al fondo, corrida por el sidebar. */
            className="fixed inset-x-0 bottom-[calc(58px+env(safe-area-inset-bottom)+12px)] z-30 px-4 lg:bottom-4 lg:left-56"
          >
            <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-sumi)] px-4 py-3 shadow-[var(--shadow-lift)]">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-white">
                  {selected.size}件を選択中
                </p>
                <p className="tabular text-xs text-white/70">
                  合計（comprobantes, antes del reparto） {formatYen(selectedTotal)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={clearSelection}
                  className="rounded-[var(--radius-pill)] px-3 py-2 text-xs font-medium text-white/70 transition-colors hover:text-white"
                >
                  解除
                </button>
                <button
                  type="button"
                  onClick={handleBatch}
                  disabled={isReadOnly || batch.isPending || allocationSaving || accountSaving || registrationSaving}
                  aria-label={`${selected.size}件をまとめて承認`}
                  className="flex shrink-0 items-center gap-2 whitespace-nowrap rounded-[var(--radius-pill)] bg-[var(--color-shuiro)] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-shuiro-deep)] disabled:opacity-70"
                >
                  <Icon name="check" className="h-4 w-4" />
                  {/* El conteo ya se ve en "○件を選択中": en movil acortamos a
                      "まとめて承認" para que no rompa a 2 lineas en 390px. */}
                  {batch.isPending ? (
                    "承認中…"
                  ) : (
                    <>
                      <span className="hidden sm:inline">
                        {selected.size}件を
                      </span>
                      まとめて承認
                    </>
                  )}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
