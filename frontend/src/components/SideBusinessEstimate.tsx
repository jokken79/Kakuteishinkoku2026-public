import { useState } from "react";
import { MixedExpenseCalculator } from "./MixedExpenseCalculator";

const inputClass = "w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-paper)] px-3 py-2 text-[var(--color-sumi)]";

/** A planning aid, not a classification or a tax return. */
export function SideBusinessEstimate() {
  const [revenue, setRevenue] = useState("");
  const [expenses, setExpenses] = useState("");
  const valid = (value: string) => value !== "" && Number.isSafeInteger(Number(value)) && Number(value) >= 0 && Number(value) <= 999_999_999;
  const result = valid(revenue) && valid(expenses) ? Number(revenue) - Number(expenses) : null;

  return <details className="rounded-lg border border-[var(--color-hairline)] p-4">
    <summary className="cursor-pointer font-bold">Calcular una orientación para mi 副業</summary>
    <div className="mt-3 space-y-3">
      <p>Introduce los ingresos y únicamente la parte de los gastos que corresponda a la actividad. Este cálculo no determina por sí solo el resultado fiscal definitivo.</p>
      <MixedExpenseCalculator onUseAsTotal={(amount) => {
        if (expenses !== "" && !window.confirm("Se sustituirá el total de gastos de esta orientación. ¿Continuar?")) return;
        setExpenses(String(amount));
      }} />
      <label className="block space-y-1"><span>Ingresos de la actividad en 2026 (¥)</span><input className={inputClass} type="number" min="0" max="999999999" step="1" value={revenue} onChange={(event) => setRevenue(event.target.value)} /></label>
      <label className="block space-y-1"><span>Gastos atribuibles a la actividad en 2026 (¥)</span><input className={inputClass} type="number" min="0" max="999999999" step="1" value={expenses} onChange={(event) => setExpenses(event.target.value)} /></label>
      {result !== null && <p role="status" className="font-bold">Resultado orientativo: {result < 0 ? "pérdida" : "beneficio"} ¥{Math.abs(result).toLocaleString("ja-JP")}</p>}
      <p>El 車検, seguro o impuestos del vehículo solo pueden incluir la parte atribuible al trabajo, si cumplen los requisitos. Conserva comprobantes y una justificación del reparto; no todos los gastos se deducen íntegramente de inmediato.</p>
      <p>Si hay pérdida, una pérdida admisible de 事業所得 puede compensarse con otros ingresos; una pérdida de 雑所得 no se resta del salario. La clasificación depende de la actividad real: tener 青色申告 no demuestra por sí solo que cualquier gasto o pérdida sea admisible.</p>
      <p>Esta orientación no incorpora todos los ajustes, depreciación, arrastres ni otras reglas. No rellena el PDF. Si hay pérdida o dudas, deja sin confirmar el cálculo automático y revisa el caso al preparar 確定申告.</p>
      <a className="underline" href="https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/2250.htm" target="_blank" rel="noopener noreferrer">Reglas de compensación de pérdidas de 国税庁</a>
    </div>
  </details>;
}
