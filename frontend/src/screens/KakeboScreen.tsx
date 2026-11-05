/**
 * 家計簿 — libro de gastos PERSONALES (NO fiscal). Pantalla aditiva: NO toca la
 * declaración ni ningún número fiscal. Muestra el resumen del mes (total +
 * desglose por 費目 con gráfico de torta), la lista de gastos del mes y un
 * formulario de alta con selector visual de categorías (emoji).
 */
import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import {
  useCreateHouseholdExpense,
  useDeleteHouseholdExpense,
  useHouseholdExpenses,
  useHouseholdSummary,
} from "../lib/hooks";
import {
  HOUSEHOLD_CATEGORIES,
  HOUSEHOLD_CATEGORY_COLORS,
  householdCategory,
  type HouseholdCategoryId,
} from "../lib/householdCategories";
import { formatDate, formatYen } from "../lib/format";
import { Card, EmptyState, ErrorState, Label, Skeleton } from "../components/ui";
import { Icon } from "../components/Icon";
import { HelpSubtitle, HelpTerm } from "../components/HelpTerm";
import { screenVariants } from "../variants/layoutVariants";
import {
  categoryPickVariants,
  expenseRowVariants,
} from "../variants/householdVariants";

/** Mes actual como `{ year, month }` (month 1-12). */
function currentYearMonth(): { year: number; month: number } {
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth() + 1 };
}

/** Fecha de hoy en formato ISO `YYYY-MM-DD` (para el default del form). */
function todayISO(): string {
  const now = new Date();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${m}-${d}`;
}

export function KakeboScreen() {
  const [{ year, month }, setPeriod] = useState(currentYearMonth);

  const expenses = useHouseholdExpenses(year, month);
  const summary = useHouseholdSummary(year, month);
  const createExpense = useCreateHouseholdExpense(year, month);
  const deleteExpense = useDeleteHouseholdExpense(year, month);

  // --- Estado del formulario de alta ---
  const [category, setCategory] = useState<HouseholdCategoryId>("shokuhi");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayISO);
  const [memo, setMemo] = useState("");

  const total = summary.data?.total ?? 0;
  const byCategory = useMemo(() => summary.data?.by_category ?? [], [summary.data]);

  const pieData = useMemo(
    () =>
      byCategory.map((c) => {
        const cat = householdCategory(c.category);
        return {
          id: cat.id,
          name: `${cat.emoji} ${cat.labelJa}`,
          value: c.total,
        };
      }),
    [byCategory],
  );

  const items = expenses.data ?? [];

  const shiftMonth = (delta: number) => {
    setPeriod((prev) => {
      const base = new Date(prev.year, prev.month - 1 + delta, 1);
      return { year: base.getFullYear(), month: base.getMonth() + 1 };
    });
  };

  const canSubmit =
    amount.trim() !== "" && Number(amount) > 0 && date.trim() !== "";

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    createExpense.mutate(
      {
        date,
        amount: Math.round(Number(amount)),
        category,
        memo: memo.trim() === "" ? null : memo.trim(),
      },
      {
        onSuccess: () => {
          setAmount("");
          setMemo("");
        },
      },
    );
  };

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-2xl px-4 py-6 sm:px-8 sm:py-10"
    >
      {/* Encabezado */}
      <div className="mb-5">
        <h2 className="flex items-center text-xl font-bold text-[var(--color-sumi)]">
          家計簿
          <HelpTerm term="家計簿" size="md" />
        </h2>
        <HelpSubtitle>
          Gastos personales (no entran a la declaración)
        </HelpSubtitle>
        <p className="mt-1 text-sm text-[var(--color-sumi-soft)]">
          確定申告には含まれない、ふだんの支出をざっくり記録します。
        </p>
      </div>

      {/* Selector de mes */}
      <div className="mb-5 flex items-center justify-between rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-4 py-3">
        <button
          type="button"
          onClick={() => shiftMonth(-1)}
          aria-label="前の月"
          className="grid h-8 w-8 place-items-center rounded-full text-[var(--color-sumi-soft)] transition-colors hover:bg-[var(--color-paper-sink)]"
        >
          <Icon name="arrow" className="h-4 w-4 rotate-180" />
        </button>
        <p className="tabular text-base font-semibold text-[var(--color-sumi)]">
          {year}年{month}月
        </p>
        <button
          type="button"
          onClick={() => shiftMonth(1)}
          aria-label="次の月"
          className="grid h-8 w-8 place-items-center rounded-full text-[var(--color-sumi-soft)] transition-colors hover:bg-[var(--color-paper-sink)]"
        >
          <Icon name="arrow" className="h-4 w-4" />
        </button>
      </div>

      {/* Resumen del mes */}
      <Card className="mb-6 p-5">
        <Label>今月の合計</Label>
        {summary.isLoading ? (
          <Skeleton className="mt-3 h-8 w-40" />
        ) : summary.isError ? (
          <ErrorState
            message="家計簿の読み込みに失敗しました。バックエンドの接続をご確認ください。"
            onRetry={() => void summary.refetch()}
          />
        ) : (
          <>
            <p className="tabular mt-1 text-3xl font-bold text-[var(--color-sumi)]">
              {formatYen(total)}
            </p>
            {total > 0 ? (
              <div className="mt-4 grid gap-4 sm:grid-cols-[180px_1fr] sm:items-center">
                {/* Gráfico de torta: altura explícita para evitar el warning
                    width/height -1 de ResponsiveContainer. */}
                <div className="h-[180px] w-full">
                  <ResponsiveContainer width="100%" height={180}>
                    <PieChart>
                      <Pie
                        data={pieData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={42}
                        outerRadius={72}
                        paddingAngle={2}
                        stroke="none"
                      >
                        {pieData.map((slice) => (
                          <Cell
                            key={slice.id}
                            fill={
                              HOUSEHOLD_CATEGORY_COLORS[
                                slice.id
                              ]
                            }
                          />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value) => [
                          formatYen(
                            typeof value === "number" ? value : Number(value),
                          ),
                          "",
                        ]}
                        contentStyle={{
                          borderRadius: 12,
                          border: "1px solid #ece8e0",
                          fontSize: 12,
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                {/* Leyenda con montos */}
                <ul className="space-y-1.5">
                  {byCategory.map((c) => {
                    const cat = householdCategory(c.category);
                    return (
                      <li
                        key={cat.id}
                        className="flex items-center justify-between gap-2 text-sm"
                      >
                        <span className="flex items-center gap-1.5 text-[var(--color-sumi)]">
                          <span
                            className="inline-block h-2.5 w-2.5 rounded-full"
                            style={{
                              backgroundColor:
                                HOUSEHOLD_CATEGORY_COLORS[cat.id],
                            }}
                            aria-hidden
                          />
                          {cat.emoji} {cat.labelJa}
                        </span>
                        <span className="tabular text-[var(--color-sumi-soft)]">
                          {formatYen(c.total)}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ) : (
              <p className="mt-2 text-sm text-[var(--color-sumi-soft)]">
                この月の記録はまだありません。下のフォームから追加できます。
              </p>
            )}
          </>
        )}
      </Card>

      {/* Formulario de alta */}
      <Card className="mb-6 p-5">
        <Label>支出を追加</Label>
        <form onSubmit={handleSubmit} className="mt-3 space-y-4">
          {/* Selector visual de 費目 (emoji) */}
          <div>
            <p className="mb-2 text-[11px] uppercase tracking-wider text-[var(--color-sumi-soft)]">
              費目
            </p>
            <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
              {HOUSEHOLD_CATEGORIES.map((c) => {
                const active = c.id === category;
                return (
                  <motion.button
                    key={c.id}
                    type="button"
                    variants={categoryPickVariants}
                    initial="rest"
                    whileTap="tap"
                    onClick={() => setCategory(c.id)}
                    aria-pressed={active}
                    aria-label={c.labelJa}
                    className={`flex flex-col items-center gap-1 rounded-[var(--radius-card)] border px-1 py-2 transition-colors ${
                      active
                        ? "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)]"
                        : "border-[var(--color-hairline)] bg-[var(--color-surface)] hover:bg-[var(--color-paper-sink)]"
                    }`}
                  >
                    <span className="text-xl leading-none" aria-hidden>
                      {c.emoji}
                    </span>
                    <span
                      className={`text-[10px] leading-tight ${
                        active
                          ? "font-medium text-[var(--color-seiji)]"
                          : "text-[var(--color-sumi-soft)]"
                      }`}
                    >
                      {c.labelJa}
                    </span>
                  </motion.button>
                );
              })}
            </div>
          </div>

          {/* Monto + fecha */}
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-[var(--color-sumi-soft)]">
                金額（円）
              </span>
              <input
                type="number"
                inputMode="numeric"
                min={1}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="1200"
                className="tabular mt-1 w-full rounded-md border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-sumi)] focus:border-[var(--color-seiji)] focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-[var(--color-sumi-soft)]">
                日付
              </span>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="tabular mt-1 w-full rounded-md border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-sumi)] focus:border-[var(--color-seiji)] focus:outline-none"
              />
            </label>
          </div>

          {/* Memo */}
          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-[var(--color-sumi-soft)]">
              メモ（任意）
            </span>
            <input
              type="text"
              value={memo}
              maxLength={255}
              onChange={(e) => setMemo(e.target.value)}
              placeholder="スーパー、ランチ など"
              className="mt-1 w-full rounded-md border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-sumi)] focus:border-[var(--color-seiji)] focus:outline-none"
            />
          </label>

          <button
            type="submit"
            disabled={!canSubmit || createExpense.isPending}
            className="flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-opacity disabled:opacity-50"
          >
            <Icon name="check" className="h-4 w-4" />
            {createExpense.isPending ? "保存中…" : "追加する"}
          </button>
        </form>
      </Card>

      {/* Lista de gastos del mes */}
      <div className="mb-3 flex items-center justify-between">
        <Label>今月の記録</Label>
        {items.length > 0 && (
          <span className="tabular text-xs text-[var(--color-sumi-soft)]">
            {items.length}件
          </span>
        )}
      </div>

      {expenses.isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      ) : expenses.isError ? (
        <Card>
          <ErrorState
            message="記録の読み込みに失敗しました。"
            onRetry={() => void expenses.refetch()}
          />
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon="book"
            title="まだ記録がありません"
            hint="上のフォームから、今月の支出を追加してみましょう。"
          />
        </Card>
      ) : (
        <div className="space-y-2">
          <AnimatePresence mode="popLayout">
            {items.map((exp) => {
              const cat = householdCategory(exp.category);
              return (
                <motion.div
                  key={exp.id}
                  layout
                  variants={expenseRowVariants}
                  initial="hidden"
                  animate="visible"
                  exit="exit"
                >
                  <Card className="flex items-center gap-3 p-3 sm:p-4">
                    <span
                      className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[var(--color-paper-sink)] text-xl"
                      aria-hidden
                    >
                      {cat.emoji}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-[var(--color-sumi)]">
                        {cat.labelJa}
                        {exp.memo && (
                          <span className="ml-2 font-normal text-[var(--color-sumi-soft)]">
                            {exp.memo}
                          </span>
                        )}
                      </p>
                      <p className="tabular mt-0.5 text-xs text-[var(--color-sumi-soft)]">
                        {formatDate(exp.date)}
                      </p>
                    </div>
                    <p className="tabular shrink-0 text-base font-bold text-[var(--color-sumi)]">
                      {formatYen(exp.amount)}
                    </p>
                    <button
                      type="button"
                      onClick={() => deleteExpense.mutate(exp.id)}
                      disabled={deleteExpense.isPending}
                      aria-label={`${cat.labelJa}の記録を削除`}
                      className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[var(--color-sumi-soft)] transition-colors hover:bg-[var(--color-kohaku-soft)] hover:text-[var(--color-kohaku)] disabled:opacity-50"
                    >
                      <span aria-hidden className="text-lg leading-none">
                        ×
                      </span>
                    </button>
                  </Card>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  );
}
