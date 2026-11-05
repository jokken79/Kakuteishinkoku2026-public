import { useState } from "react";
import { formatYen } from "../lib/format";

const field = "w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-paper)] px-3 py-2";

function wholeNumber(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed <= 1_000_000_000 ? parsed : null;
}

/** Estimación de 家事按分; no altera asientos ni decide la deducibilidad. */
export function MixedExpenseCalculator({ onUseAsTotal }: { onUseAsTotal?: (amount: number) => void } = {}) {
  const [amount, setAmount] = useState("");
  const [businessKm, setBusinessKm] = useState("");
  const [totalKm, setTotalKm] = useState("");
  const yen = wholeNumber(amount);
  const work = wholeNumber(businessKm);
  const total = wholeNumber(totalKm);
  const valid = yen !== null && work !== null && total !== null && total > 0 && work <= total;
  const businessYen = valid ? Number((BigInt(yen) * BigInt(work)) / BigInt(total)) : null;

  return (
    <details className="mb-5 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-paper)] p-4">
      <summary className="cursor-pointer font-bold">Calcular uso mixto del coche · 家事按分</summary>
      <p className="mt-3 text-sm">Introduce un gasto elegible y los kilómetros del mismo período. Conserva recibos y registros de viajes que justifiquen la proporción. El trayecto personal y al trabajo asalariado no se incluye automáticamente como uso del 副業.</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="space-y-1"><span className="text-sm">Gasto a repartir (¥)</span><input className={field} type="number" min="0" max="1000000000" step="1" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
        <label className="space-y-1"><span className="text-sm">Km de 副業</span><input className={field} type="number" min="0" max="1000000000" step="1" value={businessKm} onChange={(event) => setBusinessKm(event.target.value)} /></label>
        <label className="space-y-1"><span className="text-sm">Km totales</span><input className={field} type="number" min="1" max="1000000000" step="1" value={totalKm} onChange={(event) => setTotalKm(event.target.value)} /></label>
      </div>
      {valid && businessYen !== null ? (
        <p role="status" className="mt-3 text-sm">Proporción: {((work / total) * 100).toFixed(2)} %. Parte estimada del 副業: <strong>{formatYen(businessYen)}</strong>; parte restante: {formatYen(yen - businessYen)}. Se redondea hacia abajo al yen.</p>
      ) : (amount || businessKm || totalKm) ? (
        <p role="status" className="mt-3 text-sm">Usa números enteros: los kilómetros totales deben ser mayores que cero y no menores que los de 副業.</p>
      ) : null}
      {valid && businessYen !== null && onUseAsTotal && <button type="button" onClick={() => onUseAsTotal(businessYen)} className="mt-3 rounded border border-[var(--color-hairline)] px-3 py-2 text-sm">Usar esta parte como total de gastos del cálculo</button>}
      {onUseAsTotal && <p className="mt-2 text-sm">El botón sustituye el total de gastos de la orientación; no suma otros comprobantes ni guarda datos.</p>}
      <p className="mt-3 text-sm">Esta calculadora no registra ni cambia gastos. Para guardar el reparto, abre el comprobante pendiente y selecciona «Repartir gasto mixto por kilómetros». Si confirmas sin guardar un reparto, se suma el importe completo.</p>
      <p className="mt-2 text-sm">Revisa cada concepto: no todos los impuestos, pagos del préstamo o gastos personales son deducibles. Una pérdida de 雑所得 no se compensa con el salario; la clasificación del 副業 depende de sus circunstancias.</p>
      <a className="mt-2 inline-block text-sm underline" href="https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/2210.htm" target="_blank" rel="noreferrer">国税庁: gastos necesarios</a>
    </details>
  );
}
