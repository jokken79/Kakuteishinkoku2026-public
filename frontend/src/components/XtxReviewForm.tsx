import { useEffect, useRef, useState } from "react";

interface Context {
  year: number; name: string; address: string | null; office_code: string | null;
  name_kana: string | null; postal_code: string | null; occupation: string | null;
  sales_revenue: number; salary_revenue: number; withholding: number;
  social_insurance: number; ideco: number; life_insurance: number; earthquake_insurance: number;
}
interface Review { schema_valid: boolean | null; ready_for_submission: boolean; missing: string[] }
const insurance = [
  ["new_life", "新生命保険料"], ["old_life", "旧生命保険料"], ["care", "介護医療保険料"],
  ["new_pension", "新個人年金保険料"], ["old_pension", "旧個人年金保険料"],
  ["earthquake", "地震保険料"], ["old_damage", "旧長期損害保険料"],
] as const;
const reasons: Record<string, string> = {
  official_import_acceptance: "Falta completar la revisión fiscal de las páginas generadas por e-Tax.",
  taxpayer_my_number: "Introduce el マイナンバー completo.", taxpayer_birth_date: "Introduce 生年月日.",
  income_payers: "Añade los pagadores y las retenciones de los comprobantes.",
  monthly_sales: "Completa los doce meses de 売上.", opening_balances: "Introduce los saldos iniciales o declara que son cero.",
  business_period: "Completa el período de actividad.", tax_office_assignment: "Selecciona una 税務署 admitida en el perfil.",
  xsd_missing: "Falta instalar el árbol XSD oficial en el servidor.",
  xsd_dependency_missing: "Falta el validador XSD en el servidor.", xsd_invalid: "El documento no supera el XSD oficial.",
  details_incompatible: "Hay datos incompatibles: revisa períodos, importes, totales mensuales y balance inicial.",
  damage_contract_election: "Un mismo contrato no permite deducir a la vez terremoto y seguro antiguo: revisa la elección.",
  shiroiro_annex: "El anexo de 白色申告 todavía no está verificado para XTX.",
  unsupported_income: "Hay tipos de ingresos que necesitan anexos aún no admitidos.",
  tax_credit_allocation: "Falta clasificar y verificar los 税額控除.", balance_reconciliation: "El balance fiscal no cuadra.",
  refund_account: "La declaración tiene devolución: falta verificar la cuenta de reembolso.",
  business_loss_schedule: "La pérdida del negocio necesita revisar compensaciones y anexos.",
  inventory_schedule: "Las compras de mercancía necesitan el detalle de existencias y coste de ventas.",
};
function reason(code: string): string {
  if (reasons[code]) return reasons[code];
  const [kind, field] = code.split(":");
  if (kind === "deduction_schedule") return `Falta el anexo fiscal de ${field}.`;
  if (kind === "expense_schedule") return `Falta el detalle de gastos de la casilla ${field}.`;
  if (kind === "filing_checklist") {
    if (field === "prepayment_known") return "Confirma el importe notificado de 予定納税 en esta pantalla.";
    if (field === "forms_ready") return "Falta revisar las casillas y anexos del documento final.";
    return "Completa los requisitos pendientes de la lista de revisión de la declaración.";
  }
  if (kind?.includes("reconciliation")) return `El detalle no coincide con el cálculo: ${field ?? kind}.`;
  if (kind?.startsWith("taxpayer_")) return `Completa ${kind.slice(9)} en el perfil del contribuyente.`;
  return `Comprobación pendiente: ${code}.`;
}
const inputClass = "mt-1 block w-full rounded border border-[var(--color-hairline)] bg-[var(--color-surface)] p-2 text-sm";
function Entry({ name, label, type = "text", required = false, digits }: {
  name: string; label: string; type?: string; required?: boolean; digits?: number;
}) {
  return <label className="block text-sm">{label}<input name={name} aria-label={label} type={type}
    required={required} autoComplete={type === "password" ? "new-password" : "off"}
    className={inputClass} {...(digits ? { pattern: `[0-9]{${digits}}`, minLength: digits, maxLength: digits, inputMode: "numeric" as const } : {})}
    {...(type === "number" ? { min: 0, step: 1 } : {})} /></label>;
}
export function XtxReviewForm({ draftId }: { draftId: string }) {
  const [open, setOpen] = useState(false);
  return <section className="mt-4 border-t border-[var(--color-hairline)] pt-4">
    <h3 className="font-semibold">Preparar XTX · e-Tax</h3>
    <p className="mt-2 text-sm">Los identificadores se usan durante esta revisión. No se guardan en la base de datos ni en el almacenamiento del navegador. Al cerrar se vacían los campos.</p>
    <button type="button" className="mt-3 rounded border p-2 text-sm" onClick={() => setOpen(!open)}>
      {open ? "Cerrar y vaciar los datos XTX" : "Introducir identidad y detalles XTX"}
    </button>
    {open && <TransientForm key={draftId} draftId={draftId} />}
  </section>;
}
function TransientForm({ draftId }: { draftId: string }) {
  const [context, setContext] = useState<Context | null>(null);
  const [error, setError] = useState("");
  const [report, setReport] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [payers, setPayers] = useState(1);
  const [premiums, setPremiums] = useState(1);
  const [balances, setBalances] = useState(1);
  const [donations, setDonations] = useState(1);
  const form = useRef<HTMLFormElement>(null);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const base = `/api/v1/filing/${encodeURIComponent(draftId)}/xtx`;
  useEffect(() => {
    const controller = new AbortController();
    void fetch(`${base}/context`, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("No se pudo consultar el perfil. Revisa el ejercicio y la declaración.");
        return await response.json() as Context;
      }).then(value => { if (!controller.signal.aborted) setContext(value); })
      .catch(() => { if (!controller.signal.aborted) setError("No se pudo consultar el perfil. Reabre el formulario para reintentar."); });
    return () => { controller.abort(); active.current?.abort(); };
  }, [base]);
  function invalidate() {
    generation.current++;
    active.current?.abort();
    setReport(null); setBusy(false); setError("");
  }
  function payload() {
    if (!form.current) throw new Error("Falta el formulario.");
    const data = new FormData(form.current);
    const text = (name: string) => { const value = data.get(name); return typeof value === "string" ? value.trim() : ""; };
    const money = (name: string) => {
      const raw = text(name);
      if (!/^[0-9]+$/.test(raw) || !Number.isSafeInteger(Number(raw)))
        throw new Error("Completa cada importe del detalle con yenes enteros; escribe 0 cuando corresponda.");
      return Number(raw);
    };
    const rows = <T,>(count: number, prefix: string, fields: string[], convert: (i: number) => T) =>
      Array.from({ length: count }, (_, i) => i)
        .filter(i => fields.some(field => text(`${prefix}${i}_${field}`)))
        .map(convert);
    const opening = rows(balances, "b", ["name", "amount"], i => {
      const name = text(`b${i}_name`);
      if (!name) throw new Error("Cada saldo necesita el nombre japonés de su cuenta.");
      return [name, money(`b${i}_amount`)] as const;
    });
    if (new Set(opening.map(row => row[0])).size !== opening.length)
      throw new Error("No repitas cuentas en los saldos iniciales.");
    const zeroOpening = data.has("zero_opening");
    if (zeroOpening && opening.length) throw new Error("Elige saldos iniciales o confirma que son cero.");
    const start = text("period_start"), end = text("period_end");
    if (!!start !== !!end) throw new Error("Completa ambas fechas del período de actividad.");
    return {
      identity: { user_id: text("user_id"), my_number: text("my_number") || null, birth_date: text("birth_date") || null },
      details: {
        payers: rows(payers, "p", ["name", "location", "gross", "withholding"], i => ({
          kind: text(`p${i}_kind`), name: text(`p${i}_name`), location: text(`p${i}_location`),
          gross: money(`p${i}_gross`), withholding: money(`p${i}_withholding`),
        })),
        premiums: rows(premiums, "s", ["label", "paid", "outside"], i => ({
          category: text(`s${i}_category`), label: text(`s${i}_label`), paid: money(`s${i}_paid`),
          outside_year_end_adjustment: money(`s${i}_outside`),
        })),
        insurance: insurance.filter(([key]) => text(`${key}_paid`) || text(`${key}_outside`)).map(([category]) => ({
          category, paid: money(`${category}_paid`), outside_year_end_adjustment: money(`${category}_outside`),
        })),
        separate_damage_contracts: data.has("separate_damage_contracts"),
        donations: rows(donations, "d", ["name", "location", "paid"], i => ({
          name: text(`d${i}_name`), location: text(`d${i}_location`), paid: money(`d${i}_paid`),
        })),
        monthly_sales: Array.from({ length: 12 }, (_, i) => text(`month${i}`)).some(Boolean)
          ? Array.from({ length: 12 }, (_, i) => money(`month${i}`)) : null,
        business_period: start && end ? [start, end] : null,
        opening_balances: zeroOpening ? {} : opening.length ? Object.fromEntries(opening) : null,
      },
    };
  }
  async function run(download: boolean) {
    if (!form.current?.reportValidity() || (download && !report?.ready_for_submission)) return;
    const current = ++generation.current;
    active.current?.abort();
    const controller = new AbortController(); active.current = controller;
    setError(""); setBusy(true);
    try {
      const body = JSON.stringify(payload());
      const response = await fetch(download ? base : `${base}/review`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body,
        cache: "no-store", signal: controller.signal,
      });
      if (current !== generation.current || controller.signal.aborted) return;
      if (!response.ok) throw new Error(response.status === 409
        ? "La declaración aún no está lista para presentar. Revisa los requisitos pendientes."
        : "Revisa los dígitos ASCII, fechas, importes y nombres de los detalles.");
      if (download) {
        if (!response.headers.get("content-type")?.includes("application/xml")) throw new Error("El servidor no devolvió un archivo XTX.");
        const blob = await response.blob();
        if (current !== generation.current || controller.signal.aborted) return;
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a"); link.href = url; link.download = `shinkoku_${context?.year}.xtx`;
        link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      } else {
        const value = await response.json() as Review;
        if (current === generation.current && !controller.signal.aborted) setReport(value);
      }
    } catch (cause) {
      if (current === generation.current && !controller.signal.aborted) {
        setReport(null); setError(cause instanceof Error ? cause.message : "No se pudo revisar el XTX.");
      }
    } finally { if (current === generation.current) setBusy(false); }
  }
  return <form ref={form} autoComplete="off" onChange={invalidate} onSubmit={event => { event.preventDefault(); void run(false); }} className="mt-4 space-y-5">
    {error && <p role="alert" className="text-sm">{error}</p>}
    {!context ? <p className="text-sm">Consultando el perfil…</p> : <>
      <fieldset className="space-y-3"><legend className="font-semibold">1 · Identidad</legend>
        <p className="text-sm">{context.name} · {context.address ?? "Falta dirección"} · 税務署 {context.office_code ?? "sin asignar"}</p>
        <p className="text-sm">{context.name_kana ?? "Falta フリガナ"} · {context.postal_code ?? "Falta código postal"} · {context.occupation ?? "Falta 職業"}. Corrige estos datos en el perfil.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Entry name="user_id" label="利用者識別番号 · 16 dígitos" type="password" digits={16} required />
          <Entry name="my_number" label="マイナンバー · 12 dígitos" type="password" digits={12} />
          <Entry name="birth_date" label="生年月日 · Fecha de nacimiento" type="date" />
        </div>
      </fieldset>
      <fieldset className="space-y-3"><legend className="font-semibold">2 · Pagadores e ingresos</legend>
        <p className="text-sm">売上 {context.sales_revenue.toLocaleString()}円 · 給与 {context.salary_revenue.toLocaleString()}円 · 源泉徴収 {context.withholding.toLocaleString()}円. El detalle debe sumar estos importes.</p>
        {Array.from({ length: payers }, (_, i) => <div key={i} className="grid gap-3 rounded border p-3 sm:grid-cols-2">
          <label className="text-sm">Tipo {i + 1}<select name={`p${i}_kind`} className={inputClass}><option value="jigyo">営業等</option><option value="kyuyo">給与</option></select></label>
          <Entry name={`p${i}_name`} label={`Pagador ${i + 1}`} /><Entry name={`p${i}_location`} label={`Dirección del pagador ${i + 1}`} />
          <Entry name={`p${i}_gross`} label={`Ingreso bruto ${i + 1}`} type="number" /><Entry name={`p${i}_withholding`} label={`Retención ${i + 1}`} type="number" />
        </div>)}
        <button type="button" disabled={payers >= 40} onClick={() => { invalidate(); setPayers(payers + 1); }}>+ Añadir pagador</button>
      </fieldset>
      <fieldset className="space-y-3"><legend className="font-semibold">3 · 社会保険料 y iDeCo</legend>
        <p className="text-sm">Contabilizado: 社会保険料 {context.social_insurance.toLocaleString()}円 · iDeCo {context.ideco.toLocaleString()}円.</p>
        {Array.from({ length: premiums }, (_, i) => <div key={i} className="grid gap-3 rounded border p-3 sm:grid-cols-2">
          <label className="text-sm">Categoría {i + 1}<select name={`s${i}_category`} className={inputClass}><option value="social">社会保険料</option><option value="ideco">小規模企業共済等掛金</option></select></label>
          <Entry name={`s${i}_label`} label={`Nombre del seguro ${i + 1}`} /><Entry name={`s${i}_paid`} label={`Pagado ${i + 1}`} type="number" />
          <Entry name={`s${i}_outside`} label={`Fuera de 年末調整 ${i + 1}`} type="number" />
        </div>)}
        <button type="button" disabled={premiums >= 6} onClick={() => { invalidate(); setPremiums(premiums + 1); }}>+ Añadir seguro</button>
      </fieldset>
      <fieldset className="space-y-3"><legend className="font-semibold">4 · 生命保険料 y 地震保険料</legend>
        <p className="text-sm">Introduce las primas netas de los certificados, después de devoluciones. 控除 contabilizado: vida {context.life_insurance.toLocaleString()}円 · terremoto {context.earthquake_insurance.toLocaleString()}円.</p>
        {insurance.map(([key, label]) => <div key={key} className="grid gap-3 sm:grid-cols-2"><Entry name={`${key}_paid`} label={`${label} · Total pagado`} type="number" /><Entry name={`${key}_outside`} label={`${label} · Fuera de 年末調整`} type="number" /></div>)}
        <label className="block text-sm"><input name="separate_damage_contracts" type="checkbox" /> Los importes de 地震保険料 y 旧長期損害保険料 corresponden a contratos distintos y elegibles.</label>
      </fieldset>
      <fieldset className="space-y-3"><legend className="font-semibold">5 · ふるさと納税</legend>
        <p className="text-sm">Solo donaciones a 自治体 elegibles para 特例控除. Incluye también las declaradas por ワンストップ特例. Otros tipos de donaciones requieren revisión fuera de este formulario.</p>
        {Array.from({ length: donations }, (_, i) => <div key={i} className="grid gap-3 rounded border p-3 sm:grid-cols-2">
          <Entry name={`d${i}_name`} label={`自治体 destinatario ${i + 1}`} /><Entry name={`d${i}_location`} label={`Dirección del 自治体 ${i + 1}`} /><Entry name={`d${i}_paid`} label={`Donación ${i + 1}`} type="number" />
        </div>)}
        <button type="button" disabled={donations >= 40} onClick={() => { invalidate(); setDonations(donations + 1); }}>+ Añadir donación</button>
      </fieldset>
      <fieldset className="space-y-3"><legend className="font-semibold">6 · 青色申告決算書</legend>
        <div className="grid gap-3 sm:grid-cols-2"><Entry name="period_start" label="Inicio de actividad" type="date" /><Entry name="period_end" label="Fin de actividad" type="date" /></div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{Array.from({ length: 12 }, (_, i) => <Entry key={i} name={`month${i}`} label={`売上 · Mes ${i + 1}`} type="number" />)}</div>
        <p className="text-sm">Saldos iniciales: nombres fiscales japoneses (現金, 普通預金, 売掛金, 借入金, 元入金…). No arrastres 事業主貸 ni 事業主借.</p>
        {Array.from({ length: balances }, (_, i) => <div key={i} className="grid gap-3 sm:grid-cols-2"><Entry name={`b${i}_name`} label={`Cuenta inicial ${i + 1}`} /><Entry name={`b${i}_amount`} label={`Saldo inicial ${i + 1}`} type="number" /></div>)}
        <button type="button" disabled={balances >= 30} onClick={() => { invalidate(); setBalances(balances + 1); }}>+ Añadir saldo inicial</button>
        <label className="block text-sm"><input type="checkbox" name="zero_opening" /> Confirmo que todos los saldos iniciales son cero.</label>
      </fieldset>
      <div className="flex flex-wrap gap-3"><button type="submit" disabled={busy} className="rounded border p-3">{busy ? "Comprobando…" : "Revisar XTX"}</button>
        <button type="button" disabled={busy || !report?.ready_for_submission} onClick={() => { void run(true); }} className="rounded border p-3 disabled:opacity-50">Descargar XTX para presentar</button></div>
      {report && <div role="status" className="space-y-2 text-sm"><p>XSD oficial: {report.schema_valid === true ? "válido" : report.schema_valid === false ? "no válido" : "sin verificar"}.</p><p>{report.ready_for_submission ? "Listo para descargar." : "Descarga bloqueada. Requisitos pendientes:"}</p><ul className="list-disc space-y-1 pl-5">{report.missing.map(code => <li key={code}>{reason(code)}</li>)}</ul></div>}
    </>}
  </form>;
}
