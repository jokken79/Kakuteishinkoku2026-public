import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys, useActiveYearLock } from "../lib/hooks";
import { Card } from "./ui";

type Prepayment = { amount: number | null };

export function EstimatedPrepayment({ year }: { year: number }) {
  const query = useQuery({
    queryKey: ["estimated-prepayment", year],
    queryFn: async ({ signal }): Promise<Prepayment> => {
      const response = await fetch(`/api/v1/fiscal-years/${year}/estimated-prepayment`, { signal, cache: "no-store" });
      if (!response.ok) throw new Error("No se pudo consultar 予定納税.");
      return response.json() as Promise<Prepayment>;
    },
  });
  if (query.isLoading) return <Card className="p-4">Consultando 予定納税…</Card>;
  if (query.isError || !query.data) return <Card className="p-4">No se pudo consultar 予定納税. <button type="button" onClick={() => void query.refetch()} className="underline">Reintentar</button></Card>;
  return <PrepaymentForm key={year} year={year} initial={query.data.amount} />;
}

function PrepaymentForm({ year, initial }: { year: number; initial: number | null }) {
  const [amount, setAmount] = useState(initial === null ? "" : String(initial));
  const { isReadOnly } = useActiveYearLock();
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: async (value: number | null) => {
      const response = await fetch(`/api/v1/fiscal-years/${year}/estimated-prepayment`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ amount: value }),
      });
      if (!response.ok) throw new Error("No se pudo guardar. Comprueba el ejercicio y la conexión.");
      return response.json() as Promise<Prepayment>;
    },
    onSuccess: (data) => {
      client.setQueryData(["estimated-prepayment", year], data);
      void client.invalidateQueries({ queryKey: queryKeys.filingDraft(year) });
    },
  });
  function submit() {
    const value = amount === "" ? null : Number(amount);
    if (value !== null && (!Number.isSafeInteger(value) || value < 0 || value > 999_999_999)) return;
    if (!window.confirm("Se guardará el importe del ejercicio. Guarda una copia de seguridad de tus datos antes de continuar. ¿Guardar?")) return;
    save.mutate(value);
  }
  return <Card className="space-y-3 p-4">
    <h3 className="font-bold">予定納税 · Importe notificado</h3>
    <p className="text-sm">Introduce la suma notificada del primer y segundo período. La 国税庁 indica declarar el importe notificado aunque no se haya pagado; esto no acredita que esté pagado. Vacío significa no informado, cero significa expresamente ¥0.</p>
    <label className="block text-sm">Importe notificado en {year} (¥)
      <input className="mt-1 block w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-paper)] px-3 py-2" type="number" min="0" max="999999999" step="1" value={amount} onChange={(event) => { setAmount(event.target.value); save.reset(); }} disabled={isReadOnly || save.isPending} />
    </label>
    <button type="button" onClick={submit} disabled={isReadOnly || save.isPending} className="rounded-lg border border-[var(--color-hairline)] px-3 py-2 disabled:opacity-50">{save.isPending ? "Guardando…" : "Guardar importe"}</button>
    {initial === null && !save.isSuccess && <p role="status" className="text-sm">No informado: la estimación aún calcula ¥0 para esta partida.</p>}
    {save.isSuccess && <p role="status">Importe guardado. La estimación se actualizará.</p>}
    {save.isError && <p role="alert">{save.error.message}</p>}
    <a className="block text-sm underline" href="https://www.keisan.nta.go.jp/r6yokuaru_sp/socat1/scid0256.html" target="_blank" rel="noopener noreferrer">国税庁: 予定納税</a>
  </Card>;
}
