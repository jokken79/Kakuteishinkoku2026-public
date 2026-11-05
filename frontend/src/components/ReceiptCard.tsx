/**
 * Tarjeta "documento" de un 仕訳 propuesto: thumbnail por categoria del 勘定科目
 * (o imagen real si hay Evidence) + campos (日付/取引先/金額 en mono) + 勘定科目
 * editable (persiste via PATCH) + badge de confianza con hint de "que revisar".
 * El boton 確認 dispara el GESTO DEL SELLO (hanko) — unico uso del 朱色.
 */
import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { Transaction } from "../lib/api";
import {
  accountCategory,
  confidenceLevel,
  formatDate,
  formatYen,
  reviewHint,
  type AccountCategory,
} from "../lib/format";
import { EXPENSE_CATEGORIES, categoryForAccount } from "../lib/expenseCategories";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { HankoSeal } from "./HankoSeal";
import { HelpTerm } from "./HelpTerm";
import { Icon, type IconName } from "./Icon";
import { Card } from "./ui";
import { cardPressVariants } from "../variants/hankoVariants";

interface ReceiptCardProps {
  tx: Transaction;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  onConfirm: (id: string) => Promise<void>;
  onAllocation?: (id: string, payload: { expected_total: number; numerator: number; denominator: number; rationale: string }) => Promise<void>;
  /** Persiste el cambio de 勘定科目 (PATCH). */
  onAccountChange?: (id: string, accountCode: string) => Promise<void>;
  onRegistrationChange?: (id: string, expected: string | null, number: string) => Promise<void>;
  /** Marca el gasto como 家計 (personal): lo mueve al 家計簿 (Parte 3). */
  onMoveToHousehold?: (id: string) => void;
  disabled?: boolean;
}

/** Glifo del thumbnail segun la categoria del 勘定科目. */
const CATEGORY_ICON: Record<AccountCategory, IconName> = {
  travel: "train",
  comm: "signal",
  supplies: "box",
  meeting: "cup",
  entertain: "glass",
  books: "book",
  utility: "bolt",
  generic: "receipt",
};

export function ReceiptCard({
  tx,
  selected,
  onToggleSelect,
  onConfirm,
  onAllocation,
  onAccountChange,
  onRegistrationChange,
  onMoveToHousehold,
  disabled = false,
}: ReceiptCardProps) {
  // Normaliza al accountCode de una categoría amigable existente (si el OCR
  // sugiere un 勘定科目 sin categoría dedicada, cae a その他/599).
  const [account, setAccount] = useState(
    () => categoryForAccount(tx.account_code).accountCode,
  );
  const [stamping, setStamping] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [businessKm, setBusinessKm] = useState("");
  const [totalKm, setTotalKm] = useState("");
  const [rationale, setRationale] = useState("");
  const [allocationError, setAllocationError] = useState("");
  const [savingAllocation, setSavingAllocation] = useState(false);
  const [savingAccount, setSavingAccount] = useState(false);
  const [registrationInput, setRegistrationInput] = useState(tx.registration_number ?? "");
  const [savingRegistration, setSavingRegistration] = useState(false);
  // Origen CSV (sin OCR): el dato del banco es exacto; no aplica "alta/baja
  // confianza" ni hint de revision de lectura. Solo el 勘定科目 se revisa.
  const isCsv = tx.confidence === null || tx.confidence === undefined;
  const high = !isCsv && confidenceLevel(tx.confidence) === "high";
  const hint = isCsv ? null : reviewHint(tx.field_confidences, tx.confidence);
  const category = accountCategory(account);

  const handleAccountChange = async (next: string) => {
    if (disabled || savingAccount || !tx.id || !onAccountChange || next === account) return;
    if (!window.confirm("Se cambiará la categoría del comprobante. Haz una copia de seguridad antes de modificar datos. ¿Guardar el cambio?")) return;
    setSavingAccount(true);
    setAllocationError("");
    try {
      await onAccountChange(tx.id, next);
      setAccount(next);
    } catch {
      setAllocationError("No se pudo guardar la categoría. La selección anterior se conserva.");
    } finally {
      setSavingAccount(false);
    }
  };

  const handleConfirm = async () => {
    if (!tx.id || disabled || stamping || confirmed || savingAllocation || savingAccount || savingRegistration) return;
    const amountNotice = tx.business_allocation
      ? "Se aplicará el reparto profesional guardado."
      : "Sin reparto guardado, se incluirá el importe íntegro como gasto profesional.";
    if (!window.confirm(`${amountNotice} Verifica el uso profesional y los justificantes. Haz una copia de seguridad antes de confirmar. ¿Continuar?`)) return;
    setStamping(true);
    // Deja correr el gesto del sello antes de remover la tarjeta.
    try {
      await new Promise((r) => setTimeout(r, 520));
      await onConfirm(tx.id);
      setConfirmed(true);
    } catch {
      setAllocationError("No se pudo confirmar el comprobante. Revisa el estado del ejercicio y vuelve a intentarlo.");
    } finally {
      setStamping(false);
    }
  };

  const handleRegistration = async () => {
    const number = registrationInput.trim().toUpperCase();
    if (!tx.id || !onRegistrationChange || disabled || !/^T[0-9]{13}$/.test(number)) {
      setAllocationError("Introduce T seguido de 13 dígitos; compruébalo con el original.");
      return;
    }
    if (!window.confirm("Se corregirá el número leído del comprobante, sin verificar al emisor. Haz una copia de seguridad antes de modificar datos. ¿Guardar?")) return;
    setSavingRegistration(true);
    setAllocationError("");
    try {
      await onRegistrationChange(tx.id, tx.registration_number, number);
      setRegistrationInput(number);
    } catch {
      setAllocationError("No se pudo guardar el número. Actualiza el recibo y vuelve a revisarlo.");
    } finally {
      setSavingRegistration(false);
    }
  };

  const handleAllocation = async () => {
    const numerator = Number(businessKm);
    const denominator = Number(totalKm);
    if (!tx.id || tx.total_amount === null || !onAllocation || !/^\d+$/.test(businessKm) || !/^\d+$/.test(totalKm) || !Number.isSafeInteger(numerator) || !Number.isSafeInteger(denominator) || denominator <= 0 || numerator > denominator || denominator > 1_000_000_000 || !rationale.trim()) {
      setAllocationError("Comprueba kilómetros enteros y escribe el criterio de reparto.");
      return;
    }
    if (!window.confirm("Se guardará el reparto de este comprobante. Conviene hacer una copia de seguridad antes de modificar datos. ¿Guardar?")) return;
    setSavingAllocation(true);
    setAllocationError("");
    try {
      await onAllocation(tx.id, { expected_total: tx.total_amount, numerator, denominator, rationale: rationale.trim() });
    } catch {
      setAllocationError("No se pudo guardar el reparto. Revisa el total y el desglose fiscal del comprobante.");
    } finally {
      setSavingAllocation(false);
    }
  };

  return (
    <motion.div
      variants={cardPressVariants}
      animate={stamping ? "pressed" : "rest"}
      layout
    >
      <Card
        className={`relative overflow-hidden p-4 transition-colors sm:p-5 ${selected ? "ring-1 ring-[var(--color-seiji)]" : ""}`}
      >
        {/* Overlay del sello al confirmar */}
        <AnimatePresence>
          {stamping && (
            <motion.div
              className="pointer-events-none absolute inset-0 z-10 grid place-items-center bg-[var(--color-surface)]/40 backdrop-blur-[1px]"
              exit={{ opacity: 0 }}
            >
              <HankoSeal size={92} animate />
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex gap-4">
          {/* Checkbox de seleccion para batch */}
          <label className="flex cursor-pointer items-start pt-1">
            <input
              type="checkbox"
              checked={selected}
              disabled={disabled}
              onChange={() => tx.id && onToggleSelect(tx.id)}
              className="h-4 w-4 rounded accent-[var(--color-seiji)]"
              aria-label={`${tx.vendor ?? "この仕訳"}を選択`}
            />
          </label>

          {/* Thumbnail: icono estilizado por categoria del 勘定科目. */}
          <div className="relative hidden h-20 w-16 shrink-0 overflow-hidden rounded-md border border-[var(--color-hairline)] bg-[var(--color-paper-sink)] sm:block">
            <div className="absolute inset-0 grid place-items-center text-[var(--color-sumi-soft)]">
              <Icon name={CATEGORY_ICON[category]} className="h-7 w-7" />
            </div>
            <div className="absolute inset-x-0 bottom-0 space-y-1 p-1.5">
              <div className="h-1 w-full rounded bg-[var(--color-hairline)]" />
              <div className="h-1 w-3/4 rounded bg-[var(--color-hairline)]" />
              <div className="h-1 w-1/2 rounded bg-[var(--color-hairline)]" />
            </div>
          </div>

          {/* Campos */}
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-[var(--color-sumi)]">
                  {tx.vendor ?? "（取引先 不明）"}
                </p>
                <p className="tabular mt-0.5 text-xs text-[var(--color-sumi-soft)]">
                  {formatDate(tx.date)}
                </p>
              </div>
              <ConfidenceBadge score={tx.confidence} compact />
            </div>

            <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
              {/* Monto protagonista (mono tabular) */}
              <div>
                <p className="text-[10px] uppercase tracking-wider text-[var(--color-sumi-soft)]">
                  金額（税込）
                </p>
                <p className="tabular text-xl font-bold text-[var(--color-sumi)]">
                  {formatYen(tx.total_amount)}
                </p>
              </div>

              {/* Categoría amigable editable (persiste el 勘定科目 real). */}
              <div>
                <span className="flex items-center">
                  <label
                    htmlFor={`account-${tx.id}`}
                    className="text-[10px] uppercase tracking-wider text-[var(--color-sumi-soft)]"
                  >
                    カテゴリ
                  </label>
                  <HelpTerm term="勘定科目" />
                </span>
                <div className="mt-0.5 flex items-center gap-1">
                  <Icon name="edit" className="h-3.5 w-3.5 text-[var(--color-sumi-soft)]" />
                  <select
                    id={`account-${tx.id}`}
                    value={account}
                    disabled={disabled || savingAccount || !onAccountChange}
                    onChange={(e) => void handleAccountChange(e.target.value)}
                    className="rounded-md border border-[var(--color-hairline)] bg-[var(--color-surface)] px-2 py-1 text-sm text-[var(--color-sumi)] focus:border-[var(--color-seiji)]"
                    aria-label="カテゴリを選択"
                  >
                    {EXPENSE_CATEGORIES.map((c) => (
                      <option key={c.id} value={c.accountCode}>
                        {c.emoji} {c.labelJa}
                      </option>
                    ))}
                  </select>
                </div>
                {tx.account_code && account !== tx.account_code && <p className="mt-1 text-xs">Código registrado: {tx.account_code}. La categoría mostrada es una aproximación; selecciona una categoría para cambiarla.</p>}
              </div>
            </div>

            {/* 適格請求書 / tasas */}
            {(tx.registration_number || tx.tax_lines.length > 0) && (
              <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-[var(--color-sumi-soft)]">
                {tx.registration_number && <span className="tabular rounded-full bg-[var(--color-paper-sink)] px-2 py-0.5">登録番号 leído: {tx.registration_number}</span>}
                {tx.is_qualified_invoice && (
                  <span className="inline-flex items-center rounded-full bg-[var(--color-seiji-soft)] px-2 py-0.5 text-[var(--color-seiji)]">
                    インボイス候補（未検証）
                    <HelpTerm term="適格請求書" />
                  </span>
                )}
                {tx.tax_lines.map((l, i) => (
                  <span key={i} className="tabular rounded-full bg-[var(--color-paper-sink)] px-2 py-0.5">
                    {l.rate}% / 税{formatYen(l.tax ?? 0)}
                  </span>
                ))}
              </div>
            )}
            {(tx.is_qualified_invoice || tx.registration_number) && <p className="mt-1 text-xs text-[var(--color-sumi-soft)]">Compara el número con el comprobante original; el OCR puede equivocarse. Este indicador no verifica el registro, la identidad ni la factura. Consulta el <a className="underline" href="https://www.invoice-kohyo.nta.go.jp/" target="_blank" rel="noopener noreferrer">sitio de 国税庁</a> y revisa su validez en la fecha de la operación.</p>}
            {onRegistrationChange && <details className="mt-2 text-sm">
              <summary className="cursor-pointer underline">Corregir 登録番号 leído</summary>
              <label className="mt-2 block">Número del documento (T + 13 dígitos)
                <input value={registrationInput} maxLength={14} disabled={disabled || savingRegistration}
                  onChange={(event) => setRegistrationInput(event.target.value)}
                  className="mt-1 w-full rounded border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2" />
              </label>
              <p className="mt-1 text-xs">La corrección no autentica la factura ni modifica la imagen original.</p>
              <button type="button" disabled={disabled || savingRegistration} onClick={() => void handleRegistration()} className="mt-2 underline disabled:opacity-50">Guardar número corregido</button>
            </details>}

            <p className="mt-3 text-sm text-[var(--color-sumi-soft)]">
              {tx.business_allocation
                ? `Importe profesional según reparto guardado: ${formatYen(Number(BigInt(tx.business_allocation.original_total) * BigInt(tx.business_allocation.numerator) / BigInt(tx.business_allocation.denominator)))}.`
                : "Sin reparto guardado: confirmar incluirá el importe íntegro como gasto profesional."}
            </p>
            {onAllocation && <details className="mt-3 rounded-lg border border-[var(--color-hairline)] p-3">
              <summary className="cursor-pointer text-sm font-semibold">Repartir gasto mixto por kilómetros</summary>
              {tx.business_allocation && <p className="mt-2 text-sm">Reparto guardado: {tx.business_allocation.numerator} / {tx.business_allocation.denominator}. Parte profesional: {formatYen(Number(BigInt(tx.business_allocation.original_total) * BigInt(tx.business_allocation.numerator) / BigInt(tx.business_allocation.denominator)))}. Motivo: {tx.business_allocation.rationale}</p>}
              <p className="mt-2 text-sm">El total del comprobante se conserva. El importe profesional se calculará por separado. Guarda los registros que justifican el reparto.</p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <label className="text-sm">Km de 副業<input type="number" min="0" step="1" value={businessKm} disabled={disabled || savingAllocation} onChange={(event) => setBusinessKm(event.target.value)} className="w-full rounded border border-[var(--color-hairline)] bg-[var(--color-paper)] p-2" /></label>
                <label className="text-sm">Km totales<input type="number" min="1" step="1" value={totalKm} disabled={disabled || savingAllocation} onChange={(event) => setTotalKm(event.target.value)} className="w-full rounded border border-[var(--color-hairline)] bg-[var(--color-paper)] p-2" /></label>
              </div>
              <label className="mt-2 block text-sm">Criterio y período<input value={rationale} maxLength={500} disabled={disabled || savingAllocation} onChange={(event) => setRationale(event.target.value)} className="w-full rounded border border-[var(--color-hairline)] bg-[var(--color-paper)] p-2" placeholder="Registro de viajes de 2026" /></label>
              <button type="button" disabled={disabled || savingAllocation} onClick={() => void handleAllocation()} className="mt-3 rounded bg-[var(--color-sumi)] px-3 py-2 text-sm text-white disabled:opacity-50">Guardar reparto</button>
            </details>}

            {/* Boton 確認 = estampar el sello (unico 朱色) + hint de revision */}
            <div className="mt-4 flex items-center gap-3">
              <button
                type="button"
                onClick={() => void handleConfirm()}
                disabled={disabled || stamping || confirmed || savingAllocation || savingAccount || savingRegistration}
                aria-label={`${tx.vendor ?? "この仕訳"}を確認して承認`}
                className="flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-shuiro)] px-5 py-2 text-sm font-semibold text-white shadow-[var(--shadow-paper)] transition-all hover:bg-[var(--color-shuiro-deep)] disabled:opacity-70"
              >
                <Icon name="check" className="h-4 w-4" />
                確認
              </button>
              {/* Puente 事業→家計: marcar este gasto como personal (Parte 3). */}
              {onMoveToHousehold && (
                <button
                  type="button"
                  onClick={() => tx.id && onMoveToHousehold(tx.id)}
                  disabled={disabled || stamping || confirmed}
                  aria-label="この支出は家計（個人）です"
                  className="rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3 py-2 text-xs font-medium text-[var(--color-sumi-soft)] transition-colors hover:bg-[var(--color-paper-sink)] hover:text-[var(--color-sumi)] disabled:opacity-50"
                >
                  家計に移動
                </button>
              )}
              {!high && hint && (
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--color-kohaku)]">
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-kohaku)]"
                    aria-hidden
                  />
                  {hint}
                </span>
              )}
            </div>
            {allocationError && <p role="alert" className="mt-2 text-sm">{allocationError}</p>}
          </div>
        </div>
      </Card>
    </motion.div>
  );
}
