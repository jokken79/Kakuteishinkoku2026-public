import { useState, type FormEvent } from "react";
import { createManualExpense, type FiscalYearItem } from "../lib/api";
import { EXPENSE_CATEGORIES } from "../lib/expenseCategories";
import { Card } from "./ui";

export function ManualBusinessExpense({ fiscalYear, onSaved }: {
  fiscalYear: FiscalYearItem | undefined; onSaved: () => void;
}) {
  const [date, setDate] = useState("");
  const [vendor, setVendor] = useState("");
  const [amount, setAmount] = useState("");
  const [accountCode, setAccountCode] = useState("599");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!fiscalYear || fiscalYear.status !== "open" || busy) return;
    if (Number(date.slice(0, 4)) !== fiscalYear.year) {
      setMessage("La fecha debe pertenecer al ejercicio seleccionado.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await createManualExpense({ year: fiscalYear.year, date, vendor, total_amount: Number(amount), account_code: accountCode });
      setVendor(""); setAmount("");
      setMessage("Guardado para revisión. Comprueba el reparto profesional antes de aprobarlo.");
      onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo guardar el gasto.");
    } finally { setBusy(false); }
  }

  return <Card className="mb-4 p-4">
    <details>
      <summary className="cursor-pointer font-semibold">＋ 経費を手入力 / Añadir gasto del negocio</summary>
      <p className="mt-2 text-sm">Ejercicio: {fiscalYear?.year ?? "—"}. Registra cada gasto real y conserva su comprobante. Si es mixto, indica después el porcentaje profesional.</p>
      <form onSubmit={(event) => void submit(event)} className="mt-3 grid gap-3">
        <label className="text-sm">Fecha<input required type="date" value={date} min={fiscalYear ? `${fiscalYear.year}-01-01` : undefined} max={fiscalYear ? `${fiscalYear.year}-12-31` : undefined} onChange={(e) => setDate(e.target.value)} className="block w-full rounded border p-2" /></label>
        <label className="text-sm">Proveedor o concepto<input required maxLength={255} value={vendor} onChange={(e) => setVendor(e.target.value)} className="block w-full rounded border p-2" /></label>
        <label className="text-sm">Importe total en yenes<input required type="number" min="1" max="2000000000" step="1" value={amount} onChange={(e) => setAmount(e.target.value)} className="block w-full rounded border p-2" /></label>
        <label className="text-sm">Categoría<select value={accountCode} onChange={(e) => setAccountCode(e.target.value)} className="block w-full rounded border p-2">{EXPENSE_CATEGORIES.map((category) => <option key={category.id} value={category.accountCode}>{category.labelJa} / {category.labelEs}</option>)}</select></label>
        <button disabled={!fiscalYear || fiscalYear.status !== "open" || busy} className="rounded bg-[var(--color-sumi)] px-4 py-2 text-white disabled:opacity-50">{busy ? "Guardando…" : "Guardar para revisión"}</button>
      </form>
      {message && <p role="status" className="mt-2 text-sm">{message}</p>}
    </details>
  </Card>;
}
