import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FILING_TYPE_OPTIONS, type FilingType } from "../lib/incomeFiling";
import { Card } from "./ui";
import { queryKeys } from "../lib/hooks";

type Current = { value: FilingType; source: "year" | "profile_unconfirmed" };

export function FilingTypeByYear({ year, readOnly, onSaved }: {
  year: number; readOnly: boolean; onSaved: () => void;
}) {
  const [current, setCurrent] = useState<Current | null>(null);
  const [selection, setSelection] = useState<"" | FilingType>("");
  const [backup, setBackup] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const queryClient = useQueryClient();

  useEffect(() => {
    const abort = new AbortController();
    fetch(`/api/v1/fiscal-years/${year}/filing-type`, { signal: abort.signal, cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error();
        return response.json() as Promise<Current>;
      })
      .then(setCurrent)
      .catch(() => { if (!abort.signal.aborted) setMessage("No se pudo consultar la modalidad del ejercicio."); });
    return () => abort.abort();
  }, [year]);

  async function save() {
    if (!selection || !backup || busy || readOnly) return;
    if (!window.confirm(`Se guardará la modalidad elegida solo para ${year}. El cálculo puede cambiar. ¿Continuar?`)) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`/api/v1/fiscal-years/${year}/filing-type`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: selection, backup_confirmed: true }),
      });
      if (!response.ok) throw new Error();
      setCurrent(await response.json() as Current);
      setSelection("");
      setBackup(false);
      setMessage("Modalidad guardada para este ejercicio. Comprueba el resultado del recálculo.");
      void queryClient.invalidateQueries({ queryKey: queryKeys.recommendations(year) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.deductionSuggestions(year) });
      onSaved();
    } catch {
      setMessage("No se pudo guardar la modalidad. Comprueba que el ejercicio siga abierto y vuelve a intentarlo.");
    } finally {
      setBusy(false);
    }
  }

  const label = FILING_TYPE_OPTIONS.find((item) => item.value === current?.value)?.label;
  return (
    <Card className="p-4 text-sm leading-relaxed">
      <h3 className="font-semibold">申告区分 · Modalidad de {year}</h3>
      {current && <p className="mt-2">En el cálculo: {label ?? "desconocida"}. {current.source === "year" ? "Confirmada para este año." : "Heredada del perfil: no está confirmada para este año."}</p>}
      <p className="mt-1">Comprueba los requisitos de 青色申告 y los documentos de este ejercicio; elegir una modalidad no demuestra que tengas derecho a la deducción.</p>
      {!readOnly && current && <div className="mt-3 space-y-3">
        <label className="block">Elegir modalidad para {year}
          <select className="mt-1 block w-full rounded border border-[var(--color-hairline)] bg-white p-2" value={selection} onChange={(event) => setSelection(event.target.value as "" | FilingType)}>
            <option value="">Selecciona una opción</option>
            {FILING_TYPE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
        <label className="flex items-start gap-2"><input type="checkbox" checked={backup} onChange={(event) => setBackup(event.target.checked)} />He hecho una copia de seguridad y revisado la modalidad de este año.</label>
        <button type="button" disabled={!selection || !backup || busy} onClick={() => void save()} className="rounded bg-[var(--color-sumi)] px-4 py-2 font-semibold text-white disabled:opacity-50">Guardar modalidad de {year}</button>
      </div>}
      {readOnly && <p className="mt-2">Ejercicio cerrado o presentado: no se puede cambiar aquí.</p>}
      {message && <p role="status" className="mt-2">{message}</p>}
    </Card>
  );
}
