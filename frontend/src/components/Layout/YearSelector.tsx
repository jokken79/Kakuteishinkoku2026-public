/**
 * Selector de 年度 del header. Muestra el año fiscal activo del ciclo multi-año
 * y, al abrir, la lista de años disponibles (de `GET /fiscal-years`) + la acción
 * "新しい年度を開始" para abrir un año nuevo (POST). Al cambiar de año, todos los
 * datos de la app reflejan ese 年度 (los hooks leen `activeYear` del store).
 *
 * Diseño "Calma fiscal": dropdown sereno (sumi/seiji), sin shuiro (reservado al
 * sello/confirmación). Accesible por teclado (Escape + click-fuera). Ayuda ES.
 */
import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  useCreateFiscalYear,
  useFiscalYears,
  useOpeningBalances,
  useUpsertOpeningBalances,
} from "../../lib/hooks";
import { useUiStore } from "../../lib/store";
import { formatYen, toReiwa } from "../../lib/format";
import { Icon } from "../Icon";
import { HelpSubtitle, HelpTerm } from "../HelpTerm";
import { yearMenuVariants } from "../../variants/yearSelectorVariants";

/** Etiqueta japonesa del status del 年度 (open/closed/filed). */
const STATUS_LABEL: Record<string, string> = {
  open: "受付中",
  closed: "締切済み",
  filed: "申告済み",
};

const OPENING_BALANCE_FIELDS = [
  { code: "101", label: "現金", category: "asset" },
  { code: "102", label: "普通預金", category: "asset" },
  { code: "135", label: "売掛金", category: "asset" },
  { code: "201", label: "買掛金", category: "liability" },
  { code: "205", label: "未払金", category: "liability" },
  { code: "301", label: "元入金", category: "equity" },
] as const;

type OpeningBalanceCode = (typeof OPENING_BALANCE_FIELDS)[number]["code"];
type OpeningBalanceDraft = Record<OpeningBalanceCode, string>;

const EMPTY_OPENING_BALANCE: OpeningBalanceDraft = {
  "101": "",
  "102": "",
  "135": "",
  "201": "",
  "205": "",
  "301": "",
};

const OPENING_BALANCE_MAX = 100_000_000;

function parseYenInput(value: string): number {
  const normalized = value.replace(/[^\d]/g, "");
  return normalized === "" ? 0 : Number(normalized);
}

function draftAmount(draft: OpeningBalanceDraft, code: OpeningBalanceCode): number {
  return parseYenInput(draft[code]);
}

export function YearSelector() {
  const activeYear = useUiStore((s) => s.activeYear);
  const setActiveYear = useUiStore((s) => s.setActiveYear);
  const { data } = useFiscalYears();
  const createYear = useCreateFiscalYear();

  const [open, setOpen] = useState(false);
  const [openingYear, setOpeningYear] = useState<number | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  // Evita re-sincronizar el año en cada render: solo la primera vez que llega.
  const synced = useRef(false);

  const years = useMemo(() => data?.years ?? [], [data]);
  const activeFiscalYear = years.find((fy) => fy.year === activeYear);
  const openingFiscalYear = years.find((fy) => fy.year === openingYear);
  const activeYearEditable = activeFiscalYear == null || activeFiscalYear.status === "open";

  // Sincroniza el año activo persistido con lo que conoce el backend: si el año
  // guardado no existe entre los 年度 disponibles, cae al `active_year` (OPEN más
  // reciente) que devuelve el backend. Así, con un solo año (2025) la app sigue
  // mostrando 2025 sin que el usuario tenga que tocar nada.
  useEffect(() => {
    if (synced.current || data == null) return;
    synced.current = true;
    const current = years.find((y) => y.year === activeYear);
    if ((current == null || !current.rules_available) && data.active_year != null) {
      setActiveYear(data.active_year);
    }
  }, [data, years, activeYear, setActiveYear]);

  // Cierre por click-fuera y Escape (dropdown accesible).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const selectYear = (year: number) => {
    setActiveYear(year);
    setOpen(false);
  };

  // Abre el siguiente año al más reciente conocido (o el año en curso del activo
  // si la lista está vacía). Idempotente en backend; deja ese año como activo.
  const startNextYear = () => {
    const maxYear = years.reduce((m, y) => Math.max(m, y.year), activeYear);
    createYear.mutate(maxYear + 1, {
      onSuccess: (fy) => {
        setOpen(false);
        setOpeningYear(fy.year);
      },
    });
  };

  const openOpeningDialog = (year: number) => {
    setOpeningYear(year);
    setOpen(false);
  };

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`年度の選択（現在 ${toReiwa(activeYear)}分）`}
        className="flex shrink-0 items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-2 py-1.5 text-left transition-colors hover:border-[var(--color-seiji)] sm:px-3"
      >
        <span className="leading-tight">
          <span className="block whitespace-nowrap text-[13px] font-semibold tracking-tight text-[var(--color-sumi)]">
            {toReiwa(activeYear)}分
          </span>
          <span className="block whitespace-nowrap text-[10px] tabular text-[var(--color-sumi-soft)]">
            {activeYear}年度
          </span>
        </span>
        <Icon
          name="arrow"
          className={`h-3.5 w-3.5 shrink-0 text-[var(--color-sumi-soft)] transition-transform ${open ? "rotate-90" : "rotate-90"}`}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            id={menuId}
            role="listbox"
            variants={yearMenuVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="absolute left-0 top-full z-40 mt-1.5 w-56 rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] p-1.5 shadow-[var(--shadow-lift)]"
          >
            <p className="px-2.5 pb-1 pt-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--color-sumi-soft)]">
              年度を選択
            </p>
            <HelpSubtitle className="px-2.5 pb-1">
              Elegí el año fiscal a ver
            </HelpSubtitle>

            {years.length === 0 ? (
              <p className="px-2.5 py-2 text-xs text-[var(--color-sumi-soft)]">
                年度がまだありません。
              </p>
            ) : (
              years.map((fy) => {
                const selected = fy.year === activeYear;
                return (
                  <button
                    key={fy.year}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onClick={() =>
                      fy.rules_available ? selectYear(fy.year) : openOpeningDialog(fy.year)
                    }
                    className={`flex w-full items-center justify-between gap-2 rounded-[8px] px-2.5 py-2 text-left text-sm transition-colors ${
                      selected
                        ? "bg-[var(--color-seiji-soft)] font-semibold text-[var(--color-seiji)]"
                        : "text-[var(--color-sumi)] hover:bg-[var(--color-paper-sink)]"
                    }`}
                  >
                    <span className="flex items-baseline gap-1.5">
                      <span className="tabular">{fy.year}</span>
                      <span className="text-[11px] text-[var(--color-sumi-soft)]">
                        {toReiwa(fy.year)}分
                      </span>
                    </span>
                    <span className="text-[10px] text-[var(--color-sumi-soft)]">
                      {fy.rules_available
                        ? (STATUS_LABEL[fy.status] ?? fy.status)
                        : "税制未設定"}
                    </span>
                  </button>
                );
              })
            )}

            <div className="my-1 h-px bg-[var(--color-hairline)]" />

            {createYear.isError && (
              <p role="alert" className="px-2.5 py-2 text-sm text-[var(--color-sumi)]">
                No se pudo abrir el año fiscal. Comprueba la conexión y vuelve a intentarlo.
              </p>
            )}

            <button
              type="button"
              onClick={() => openOpeningDialog(activeYear)}
              className="flex w-full items-center gap-2 rounded-[8px] px-2.5 py-2 text-left text-sm text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
            >
              <Icon name="box" className="h-4 w-4 shrink-0 text-[var(--color-seiji)]" />
              <span>
                <span className="block font-medium">
                  {activeYearEditable ? "期首残高を入力" : "期首残高を確認"}
                </span>
                <HelpSubtitle>
                  {activeYearEditable
                    ? "Ajustar saldos iniciales"
                    : "Consultar saldos del año cerrado"}
                </HelpSubtitle>
              </span>
            </button>

            <button
              type="button"
              onClick={startNextYear}
              disabled={createYear.isPending}
              className="flex w-full items-center gap-2 rounded-[8px] px-2.5 py-2 text-left text-sm text-[var(--color-seiji)] transition-colors hover:bg-[var(--color-paper-sink)] disabled:opacity-50"
            >
              <Icon name="check" className="h-4 w-4 shrink-0" />
              <span>
                <span className="block font-medium">新しい年度を開始</span>
                <HelpSubtitle>Abrir un año fiscal nuevo</HelpSubtitle>
              </span>
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      <OpeningBalanceDialog
        year={openingYear}
        editable={openingFiscalYear == null || openingFiscalYear.status === "open"}
        onClose={() => setOpeningYear(null)}
      />
    </div>
  );
}

function OpeningBalanceDialog({
  year,
  editable,
  onClose,
}: {
  year: number | null;
  editable: boolean;
  onClose: () => void;
}) {
  const titleId = useId();
  const [draft, setDraft] = useState<OpeningBalanceDraft>(EMPTY_OPENING_BALANCE);
  const isOpen = year != null;
  const query = useOpeningBalances(year ?? 2025, isOpen);
  const save = useUpsertOpeningBalances(year ?? 2025);

  useEffect(() => {
    if (!isOpen) {
      setDraft(EMPTY_OPENING_BALANCE);
      return;
    }
    if (!query.data) return;
    const next = { ...EMPTY_OPENING_BALANCE };
    for (const line of query.data.balances) {
      if (line.account_code in next) {
        next[line.account_code as OpeningBalanceCode] = String(line.amount);
      }
    }
    setDraft(next);
  }, [isOpen, query.data]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen]);

  const totals = useMemo(() => {
    const totalAssets =
      draftAmount(draft, "101") + draftAmount(draft, "102") + draftAmount(draft, "135");
    const totalLiabilities = draftAmount(draft, "201") + draftAmount(draft, "205");
    const totalEquity = draftAmount(draft, "301");
    const imbalance = totalAssets - totalLiabilities - totalEquity;
    const requiredEquity = totalAssets - totalLiabilities;
    const overLimit = OPENING_BALANCE_FIELDS.some(
      (field) => draftAmount(draft, field.code) > OPENING_BALANCE_MAX,
    );
    return {
      totalAssets,
      totalLiabilities,
      totalEquity,
      imbalance,
      requiredEquity,
      overLimit,
      isBalanced: imbalance === 0 && !overLimit,
    };
  }, [draft]);

  const updateField = (code: OpeningBalanceCode, value: string) => {
    setDraft((prev) => ({
      ...prev,
      [code]: value.replace(/[^\d]/g, ""),
    }));
  };

  const adjustMotoire = () => {
    if (totals.requiredEquity < 0 || totals.requiredEquity > OPENING_BALANCE_MAX) return;
    setDraft((prev) => ({
      ...prev,
      "301": totals.requiredEquity === 0 ? "" : String(totals.requiredEquity),
    }));
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (year == null || !editable || !totals.isBalanced) return;
    save.mutate(
      OPENING_BALANCE_FIELDS.map((field) => ({
        account_code: field.code,
        amount: draftAmount(draft, field.code),
      })),
      { onSuccess: onClose },
    );
  };

  const canAutoAdjust =
    totals.requiredEquity >= 0 && totals.requiredEquity <= OPENING_BALANCE_MAX;
  const blockingMessage = totals.overLimit
    ? "1つの残高は1億円以下で入力してください。"
    : totals.imbalance === 0
      ? null
      : "資産 = 負債 + 資本 になるように調整してください。";

  const dialog = (
    <AnimatePresence>
      {isOpen && year != null && (
        <motion.div
          className="fixed inset-0 z-[80] flex items-start justify-center overflow-y-auto overscroll-contain bg-[rgba(31,35,33,0.28)] px-3 py-4 backdrop-blur-[2px] sm:px-4 sm:py-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.form
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onSubmit={submit}
            className="max-h-[calc(100dvh-2rem)] w-full max-w-3xl overflow-y-auto rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] shadow-[var(--shadow-lift)] sm:max-h-[calc(100dvh-3rem)]"
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 12, opacity: 0 }}
            transition={{ type: "spring", stiffness: 280, damping: 28 }}
          >
            <div className="flex items-start justify-between gap-4 border-b border-[var(--color-hairline)] px-5 py-4">
              <div>
                <p
                  id={titleId}
                  className="text-base font-semibold tracking-tight text-[var(--color-sumi)]"
                >
                  期首残高
                  <HelpTerm term="期首残高" />
                </p>
                <HelpSubtitle className="text-[var(--color-sumi)]">
                  {`${toReiwa(year)}分の開始時点の残高`}
                </HelpSubtitle>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="閉じる"
                className="rounded-full border border-[var(--color-hairline)] px-2.5 py-1 text-xs font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
              >
                閉じる
              </button>
            </div>

            <div className="grid gap-5 p-5 md:grid-cols-[1fr_260px]">
              <div className="space-y-3">
                {!editable && (
                  <div
                    className="rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-paper)] p-3 text-sm leading-relaxed text-[var(--color-sumi)]"
                    role="status"
                  >
                    この年度は締切済みまたは申告済みのため、期首残高は閲覧のみです。
                  </div>
                )}
                {query.isLoading ? (
                  <div className="rounded-[var(--radius-card)] border border-[var(--color-hairline)] p-4 text-sm text-[var(--color-sumi)]">
                    読み込み中です。
                  </div>
                ) : (
                  OPENING_BALANCE_FIELDS.map((field) => (
                    <label
                      key={field.code}
                      className="grid gap-1 rounded-[10px] border border-[var(--color-hairline)] px-3 py-2.5"
                    >
                      <span className="flex items-center justify-between gap-3">
                        <span className="text-sm font-medium text-[var(--color-sumi)]">
                          {field.label}
                          <HelpTerm term={field.label} />
                        </span>
                        <span className="tabular text-[11px] font-medium text-[var(--color-sumi)]">
                          {field.code}
                        </span>
                      </span>
                      <input
                        type="number"
                        inputMode="numeric"
                        min={0}
                        max={OPENING_BALANCE_MAX}
                        value={draft[field.code]}
                        onChange={(event) => updateField(field.code, event.target.value)}
                        disabled={!editable}
                        className="h-10 rounded-[8px] border border-[var(--color-hairline)] bg-[var(--color-paper)] px-3 text-right text-sm tabular text-[var(--color-sumi)] outline-none transition-colors focus:border-[var(--color-seiji)] disabled:cursor-not-allowed disabled:opacity-70"
                        aria-label={`${field.label}の期首残高`}
                        placeholder="0"
                      />
                    </label>
                  ))
                )}
              </div>

              <aside className="rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-paper)] p-4">
                <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--color-sumi)]">
                  貸借チェック
                </p>
                <div className="mt-3 space-y-2 text-sm">
                  <BalanceRow label="資産" value={totals.totalAssets} />
                  <BalanceRow label="負債" value={totals.totalLiabilities} />
                  <BalanceRow label="資本" value={totals.totalEquity} />
                  <div className="h-px bg-[var(--color-hairline)]" />
                  <BalanceRow label="差額" value={totals.imbalance} strong />
                </div>

                <div
                  className={`mt-4 rounded-[10px] px-3 py-2 text-xs leading-relaxed ${
                    totals.isBalanced
                      ? "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]"
                      : "bg-[var(--color-kohaku-soft)] text-[var(--color-kohaku)]"
                  }`}
                  role={totals.isBalanced ? "status" : "alert"}
                >
                  {totals.isBalanced ? "一致しています。" : blockingMessage}
                </div>

                <button
                  type="button"
                  onClick={adjustMotoire}
                  disabled={!editable || !canAutoAdjust}
                  className="mt-3 w-full rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3 py-2 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-surface)] disabled:opacity-45"
                >
                  元入金を差額に合わせる
                </button>
                <p className="mt-2 text-[11px] leading-relaxed text-[var(--color-sumi)]">
                  必要な元入金: {formatYen(Math.max(0, totals.requiredEquity))}
                </p>
              </aside>
            </div>

            {save.error && (
              <p className="mx-5 mb-3 rounded-[10px] bg-[var(--color-kohaku-soft)] px-3 py-2 text-sm text-[var(--color-kohaku)]">
                {save.error.message}
              </p>
            )}

            <div className="flex flex-col-reverse gap-2 border-t border-[var(--color-hairline)] px-5 py-4 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-4 py-2 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
              >
                {editable ? "キャンセル" : "閉じる"}
              </button>
              {editable && (
                <button
                  type="submit"
                  disabled={!totals.isBalanced || save.isPending || query.isLoading}
                  className="rounded-[var(--radius-pill)] bg-[var(--color-seiji)] px-4 py-2 text-sm font-semibold text-white transition-transform active:translate-y-px disabled:opacity-50"
                >
                  {save.isPending ? "保存中" : "保存"}
                </button>
              )}
            </div>
          </motion.form>
        </motion.div>
      )}
    </AnimatePresence>
  );

  return typeof document === "undefined" ? dialog : createPortal(dialog, document.body);
}

function BalanceRow({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: number;
  strong?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between gap-3 ${strong ? "font-semibold" : ""}`}
    >
      <span className="text-[var(--color-sumi)]">{label}</span>
      <span className="tabular text-[var(--color-sumi)]">{formatYen(value)}</span>
    </div>
  );
}
