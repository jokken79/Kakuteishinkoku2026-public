import { useState, type FormEvent } from "react";
import { Card } from "../components/ui";
import { SideBusinessEstimate } from "../components/SideBusinessEstimate";
import { ApiError } from "../lib/api";
import { useDeductions, useYearEndProfile } from "../lib/hooks";

const inputClass = "w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-paper)] px-3 py-2 text-[var(--color-sumi)]";

export function YearEndScreen() {
  const { data: deductions, isError: deductionsError, error: deductionsFailure } = useDeductions(2026);
  const { data: taxpayer, isError: profileError } = useYearEndProfile();
  const [name, setName] = useState("");
  const [kana, setKana] = useState("");
  const [address, setAddress] = useState("");
  const [employer, setEmployer] = useState("");
  const [hasDependent, setHasDependent] = useState(false);
  const [dependentName, setDependentName] = useState("");
  const [dependentKana, setDependentKana] = useState("");
  const [relationship, setRelationship] = useState("");
  const [birth, setBirth] = useState("");
  const [dependentAddress, setDependentAddress] = useState("");
  const [dependentIncome, setDependentIncome] = useState("");
  const [elderlyOther, setElderlyOther] = useState(false);
  const [disability, setDisability] = useState(false);
  const [disabilityDetails, setDisabilityDetails] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [salaryEstimate, setSalaryEstimate] = useState("");
  const [otherEstimate, setOtherEstimate] = useState("");
  const [completeIncome, setCompleteIncome] = useState(false);
  const [kisoBusy, setKisoBusy] = useState(false);
  const [kisoMessage, setKisoMessage] = useState("");

  function loadRegistered() {
    if (taxpayer?.name && taxpayer.name !== "—" && taxpayer.name.length <= 35) setName((current) => current || taxpayer.name);
    if (taxpayer?.name_kana && taxpayer.name_kana.length <= 35) setKana((current) => current || taxpayer.name_kana || "");
    if (taxpayer?.address && taxpayer.address.length <= 65) setAddress((current) => current || taxpayer.address || "");
    if (deductions?.deductions.some((item) => item.type === "disability_self")) setDisability(true);
    const relatives = deductions?.deductions
      .filter((item) => item.type === "fuyo")
      .flatMap((item) => Array.isArray(item.meta?.dependents) ? item.meta.dependents as unknown[] : []) ?? [];
    if (relatives.length === 1 && typeof relatives[0] === "object" && relatives[0] !== null) {
      const relative = relatives[0] as Record<string, unknown>;
      if (relative.residence === "domestic" && typeof relative.name === "string") {
        setHasDependent(true);
        setDependentName((current) => current || String(relative.name));
        if (typeof relative.relationship === "string") setRelationship((current) => current || String(relative.relationship));
        if (typeof relative.birth_date === "string") setBirth((current) => current || String(relative.birth_date));
        if (typeof relative.goukei_shotoku === "number") setDependentIncome((current) => current || String(relative.goukei_shotoku));
      }
    }
    const tooLong = Boolean(taxpayer && (taxpayer.name.length > 35 || (taxpayer.name_kana?.length ?? 0) > 35 || (taxpayer.address?.length ?? 0) > 65));
    setMessage(tooLong
      ? "Algunos datos del perfil exceden el espacio del formulario y no se copiaron. Revísalos y complétalos manualmente."
      : "Datos disponibles cargados en campos vacíos. Revisa familiar, ingresos, categoría y vigencia del 手帳; los demás datos se completan manualmente.");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/v1/year-end/2026/fuyo-draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          taxpayer_name: name,
          taxpayer_kana: kana,
          taxpayer_address: address,
          employer_name: employer,
          dependent: hasDependent ? {
            name: dependentName,
            name_kana: dependentKana,
            relationship,
            birth_date: birth || null,
            address: dependentAddress,
            income_estimate: dependentIncome === "" ? null : Number(dependentIncome),
            elderly_other: elderlyOther,
          } : null,
          disability: disability ? "ordinary" : "none",
          disability_details: disabilityDetails,
        }),
      });
      if (!response.ok) throw new Error("No se pudo crear el PDF. Revisa los datos y la conexión.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "fuyo_2026_revision.pdf";
      link.click();
      URL.revokeObjectURL(url);
      setMessage("PDF de revisión descargado. Comprueba todas las casillas antes de entregarlo.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo crear el PDF.");
    } finally {
      setBusy(false);
    }
  }

  async function downloadKiso() {
    const salary = salaryEstimate === "" ? null : Number(salaryEstimate);
    const other = otherEstimate === "" ? null : Number(otherEstimate);
    if (!name.trim() || (salary !== null && (!Number.isSafeInteger(salary) || salary < 0 || salary > 8_500_000)) ||
        (other !== null && (!Number.isSafeInteger(other) || other < 0 || other > 25_000_000)) ||
        (completeIncome && (salary === null || other === null))) {
      setKisoMessage("Revisa tu nombre y los importes enteros. Para calcular la deducción completa ambos ingresos deben estar informados.");
      return;
    }
    setKisoBusy(true);
    setKisoMessage("");
    try {
      const response = await fetch("/api/v1/year-end/2026/kiso-draft", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ taxpayer_name: name, taxpayer_kana: kana, taxpayer_address: address,
          employer_name: employer, salary_revenue: salary, other_income: other,
          complete_income_estimate: completeIncome }),
      });
      if (!response.ok) throw new Error("No se pudo generar el borrador de 基礎控除.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "kiso_2026_revision.pdf";
      link.click();
      URL.revokeObjectURL(url);
      setKisoMessage("Borrador descargado. Revisa todas las casillas y completa las que falten.");
    } catch (error) {
      setKisoMessage(error instanceof Error ? error.message : "No se pudo crear el PDF.");
    } finally {
      setKisoBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:px-8 sm:py-10">
      <header>
        <p className="text-sm text-[var(--color-sumi-soft)]">令和8年分 · 2026</p>
        <h2 className="text-2xl font-bold">年末調整: familiares y discapacidad</h2>
        <p className="mt-2">Prepara un borrador del 扶養控除等申告書 para revisarlo y entregarlo a tu empresa.</p>
      </header>
      <Card as="section" className="p-5">
        <p>El formulario no verifica por sí mismo el derecho a las deducciones. Revisa ingresos y sustento del familiar, vigencia del 手帳 y condiciones al cierre del año.</p>
        <button type="button" onClick={loadRegistered} disabled={!deductions && !taxpayer} className="mt-3 rounded-lg border border-[var(--color-hairline)] px-3 py-2 disabled:opacity-50">Cargar datos registrados de 2026</button>
        <p className="mt-2 text-sm">Se cargan campos vacíos y, si existe exactamente un familiar registrado como residente en Japón, sus datos disponibles. Si hay varios o vive fuera de Japón, complétalos manualmente.</p>
        {deductionsError && (deductionsFailure instanceof ApiError && deductionsFailure.code === "no_fiscal_year"
          ? <p>El ejercicio 2026 todavía no está registrado. Puedes completar el borrador manualmente. Para abrir el siguiente ejercicio, usa el selector de año de la parte superior y pulsa «新しい年度を開始». Si el último ejercicio registrado es 2025, se abrirá 2026; crear el ejercicio no copia automáticamente tus deducciones.</p>
          : <p role="alert">No se pudieron consultar las deducciones registradas. Puedes completar el borrador manualmente y volver a intentarlo más tarde.</p>)}
        {profileError && <p role="alert">No se pudo consultar el perfil; puedes completar tus datos manualmente.</p>}
      </Card>
      <Card as="section" className="space-y-2 p-5">
        <h3 className="font-bold">Formulario separado: 基礎控除申告書</h3>
        <p>Para solicitar la deducción básica en 年末調整 se utiliza otro formulario. Incluye la estimación de tus ingresos salariales y de otros ingresos; el borrador de familiares de esta pantalla no lo completa.</p>
        <a className="inline-block underline" href="https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_06_input.pdf" target="_blank" rel="noopener noreferrer">Descargar formulario oficial editable de 2026</a>
        <p className="text-sm text-[var(--color-sumi-soft)]">国税庁 indica que el PDF editable debe guardarse y abrirse con Adobe Reader. Revisa también las instrucciones de tu empresa.</p>
        <a className="inline-block underline" href="https://www.nta.go.jp/users/gensen/nencho/shinkokusyo/index.htm" target="_blank" rel="noopener noreferrer">Instrucciones y formularios de 国税庁</a>
      </Card>
      <form onSubmit={(event) => void submit(event)} className="space-y-5">
        <Card as="section" className="space-y-4 p-5">
          <h3 className="text-lg font-bold">1. Tus datos</h3>
          <label className="block space-y-1"><span>Nombre completo *</span><input className={inputClass} maxLength={35} required value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label className="block space-y-1"><span>Nombre en カタカナ</span><input className={inputClass} maxLength={35} value={kana} onChange={(event) => setKana(event.target.value)} /></label>
          <label className="block space-y-1"><span>Dirección actual</span><input className={inputClass} maxLength={65} value={address} onChange={(event) => setAddress(event.target.value)} /></label>
          <label className="block space-y-1"><span>Empresa</span><input className={inputClass} maxLength={45} value={employer} onChange={(event) => setEmployer(event.target.value)} /></label>
        </Card>
        <Card as="section" className="space-y-4 p-5">
          <h3 className="text-lg font-bold">2. Familiar a cargo</h3>
          <label className="flex items-center gap-2"><input type="checkbox" checked={hasDependent} onChange={(event) => setHasDependent(event.target.checked)} />Incluir un familiar</label>
          {hasDependent && <div className="space-y-4">
            <label className="block space-y-1"><span>Nombre del familiar *</span><input className={inputClass} maxLength={35} required value={dependentName} onChange={(event) => setDependentName(event.target.value)} /></label>
            <label className="block space-y-1"><span>Nombre en カタカナ</span><input className={inputClass} maxLength={35} value={dependentKana} onChange={(event) => setDependentKana(event.target.value)} /></label>
            <label className="block space-y-1"><span>Parentesco en japonés</span><input className={inputClass} maxLength={8} value={relationship} onChange={(event) => setRelationship(event.target.value)} placeholder="母" /></label>
            <label className="block space-y-1"><span>Fecha de nacimiento</span><input className={inputClass} type="date" required={elderlyOther} max={elderlyOther ? "1957-01-01" : undefined} value={birth} onChange={(event) => setBirth(event.target.value)} /></label>
            <label className="block space-y-1"><span>Dirección del familiar</span><input className={inputClass} maxLength={51} value={dependentAddress} onChange={(event) => setDependentAddress(event.target.value)} /></label>
            <label className="block space-y-1"><span>Ingreso fiscal estimado en 2026, yenes</span><input className={inputClass} type="number" min="0" max="999999999" step="1" value={dependentIncome} onChange={(event) => setDependentIncome(event.target.value)} /></label>
            <p className="text-sm text-[var(--color-sumi-soft)]">Es el 合計所得金額 estimado, no necesariamente lo que cobra en bruto. Si recibe pensión o salario, calcula primero su ingreso fiscal; no pongas cero solo porque no trabaja. Deja el campo vacío si no lo sabes.</p>
            {dependentIncome !== "" && Number(dependentIncome) > 620_000 && <p role="alert" className="rounded-lg border border-[var(--color-kohaku)] p-3 text-sm">El importe supera ¥620.000, el límite general de ingresos del 扶養親族 para 2026. Revisa la categoría y los requisitos antes de entregar el borrador; pueden existir otras deducciones para ciertos familiares.</p>}
            <a className="inline-block text-sm underline" href="https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1180.htm" target="_blank" rel="noopener noreferrer">Consultar requisitos de 扶養控除 en 国税庁</a>
            <label className="flex items-start gap-2"><input type="checkbox" checked={elderlyOther} onChange={(event) => setElderlyOther(event.target.checked)} />Mayor de 70 años, en la categoría その他 de 老人扶養親族</label>
            <p className="text-sm text-[var(--color-sumi-soft)]">Esta casilla requiere verificar tanto la edad como la categoría de convivencia. Vivir en direcciones distintas no elimina por sí solo el requisito de compartir el sustento.</p>
          </div>}
          <p className="text-sm text-[var(--color-sumi-soft)]">Este borrador cubre un familiar residente en Japón. Si tienes más familiares o viven fuera de Japón, completa sus datos y casillas especiales manualmente antes de entregarlo.</p>
        </Card>
        <Card as="section" className="space-y-4 p-5">
          <h3 className="text-lg font-bold">3. 障害者控除</h3>
          <label className="flex items-center gap-2"><input type="checkbox" checked={disability} onChange={(event) => setDisability(event.target.checked)} />Solicito la categoría ordinaria para mí</label>
          {disability && <label className="block space-y-1"><span>Tipo, grado y fecha de expedición del 手帳</span><input className={inputClass} maxLength={75} value={disabilityDetails} onChange={(event) => setDisabilityDetails(event.target.value)} placeholder="精神障害者保健福祉手帳 3級・交付日" /></label>}
          <p className="text-sm text-[var(--color-sumi-soft)]">Para 特別障害者 u otras situaciones, completa la casilla correspondiente manualmente.</p>
        </Card>
        <Card as="section" className="space-y-3 p-5">
          <h3 className="text-lg font-bold">4. Borrador de 基礎控除</h3>
          <p>Usa los datos personales de arriba. Si dejas los ingresos vacíos, sus casillas quedarán en blanco; cero solo significa cero si lo introduces expresamente.</p>
          <SideBusinessEstimate />
          <label className="block space-y-1"><span>Salario bruto anual estimado (¥)</span><input className={inputClass} type="number" min="0" max="8500000" step="1" value={salaryEstimate} onChange={(event) => setSalaryEstimate(event.target.value)} /></label>
          <label className="block space-y-1"><span>Otros ingresos fiscales netos estimados (¥)</span><input className={inputClass} type="number" min="0" max="25000000" step="1" value={otherEstimate} onChange={(event) => setOtherEstimate(event.target.value)} /></label>
          <label className="flex items-start gap-2"><input type="checkbox" checked={completeIncome} onChange={(event) => setCompleteIncome(event.target.checked)} />He revisado que estos importes incluyen todos mis ingresos fiscales para estimar la 基礎控除.</label>
          <p className="text-sm">El cálculo automático admite salario hasta ¥8.500.000 y otros ingresos netos no negativos. Si tienes una pérdida del 副業, ajustes salariales especiales u otros casos complejos, deja la estimación sin confirmar y completa el formulario con asesoramiento.</p>
          <button type="button" disabled={kisoBusy} onClick={() => void downloadKiso()} className="rounded-lg border border-[var(--color-hairline)] px-4 py-2 font-bold disabled:opacity-50">{kisoBusy ? "Preparando…" : "Descargar borrador de 基礎控除"}</button>
          {kisoMessage && <p role="status">{kisoMessage}</p>}
        </Card>
        <button disabled={busy} type="submit" className="rounded-lg bg-[var(--color-seiji)] px-5 py-3 font-bold text-white disabled:opacity-50">{busy ? "Preparando…" : "Descargar PDF oficial para revisar"}</button>
        {message && <p role="status">{message}</p>}
        <p className="text-sm text-[var(--color-sumi-soft)]">No se envía a la empresa ni se guarda en la app. Completa fecha de nacimiento propia, My Number y demás campos necesarios en el documento o según indique tu empresa.</p>
      </form>
    </main>
  );
}
