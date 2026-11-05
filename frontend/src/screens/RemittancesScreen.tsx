import { useState } from "react";
import { Card } from "../components/ui";
import { useUiStore } from "../lib/store";

const fieldClass = "w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-paper)] px-3 py-2 text-[var(--color-sumi)]";

export function RemittancesScreen() {
  const [recipient, setRecipient] = useState("");
  const [destination, setDestination] = useState("Brasil");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("JPY");
  const [purpose, setPurpose] = useState("");
  const [bankName, setBankName] = useState("");
  const [branch, setBranch] = useState("");
  const [account, setAccount] = useState("");
  const [bankCode, setBankCode] = useState("");
  const [recipientId, setRecipientId] = useState("");
  const [notice, setNotice] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("pt");
  const [reading, setReading] = useState(false);
  const [extracted, setExtracted] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [emptyPages, setEmptyPages] = useState<number[]>([]);
  const [readError, setReadError] = useState("");
  const [textDownloaded, setTextDownloaded] = useState(false);
  const navigate = useUiStore((state) => state.setActiveSection);

  function downloadDraft() {
    const lines = [
      "BORRADOR PERSONAL — NO ES COMPROBANTE BANCARIO",
      "Esta hoja no acredita una transferencia ni confirma el pago.",
      "",
      `Destinatario: ${recipient}`,
      `País: ${destination}`,
      `Importe previsto: ${amount} ${currency}`,
      `Motivo: ${purpose}`,
      `Banco o proveedor: ${bankName}`,
      `Agencia o sucursal: ${branch}`,
      `Cuenta de destino: ${account}`,
      `Código bancario, SWIFT/BIC o identificador indicado por el banco: ${bankCode}`,
      `Identificación del destinatario, si la entidad la solicita: ${recipientId}`,
      "",
      "Completa la operación con tu banco o proveedor y conserva su comprobante original.",
      "Contiene datos personales: guarda este archivo en un lugar privado.",
    ];
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "preparacion-remesa-borrador.txt";
    link.click();
    URL.revokeObjectURL(url);
    setNotice(true);
  }

  async function readDocument() {
    if (!file) return;
    setReading(true);
    setReadError("");
    setTextDownloaded(false);
    setExtracted("");
    setWarnings([]);
    setEmptyPages([]);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("language", language);
      const response = await fetch("/api/v1/remittances/read", { method: "POST", body: form });
      if (!response.ok) {
        const data = await response.json() as { detail?: unknown };
        throw new Error(typeof data.detail === "string" ? data.detail : "No se pudo leer el archivo.");
      }
      const data = await response.json() as { text: string; warnings: string[]; empty_pages?: number[] };
      setExtracted(data.text);
      setWarnings(data.warnings);
      setEmptyPages(data.empty_pages ?? []);
    } catch (error) {
      setReadError(error instanceof Error ? error.message : "No se pudo leer el archivo.");
    } finally {
      setReading(false);
    }
  }

  function downloadExtractedText() {
    const header = "TEXTO EXTRAÍDO Y EDITABLE — NO ES COMPROBANTE BANCARIO\n" +
      "La lectura puede contener errores y no verifica autenticidad ni pago.\n\n";
    const url = URL.createObjectURL(new Blob([header, extracted], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "lectura-remesa-no-verificada.txt";
    link.click();
    URL.revokeObjectURL(url);
    setTextDownloaded(true);
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <header>
        <p className="text-sm text-[var(--color-sumi-soft)]">海外送金 · Brasil y otros países</p>
        <h2 className="mt-1 text-2xl font-bold text-[var(--color-sumi)]">Prepara y comprueba tu remesa</h2>
        <p className="mt-2 text-[var(--color-sumi-soft)]">Sigue tres pasos: prepara los datos, realiza el envío con tu banco y guarda el comprobante real.</p>
      </header>
      <Card as="section" className="space-y-4 p-5">
        <h3 className="text-lg font-bold">1. Preparar el envío</h3>
        <p>Este borrador es para tu organización. No realiza ninguna transferencia y no es un comprobante bancario.</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1"><span>Nombre del destinatario</span><input className={fieldClass} value={recipient} onChange={(event) => setRecipient(event.target.value)} autoComplete="off" /></label>
          <label className="space-y-1"><span>País de destino</span><input className={fieldClass} value={destination} onChange={(event) => setDestination(event.target.value)} /></label>
          <label className="space-y-1"><span>Importe previsto</span><input className={fieldClass} type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
          <label className="space-y-1"><span>Moneda</span><select className={fieldClass} value={currency} onChange={(event) => setCurrency(event.target.value)}><option>JPY</option><option>BRL</option><option>USD</option></select></label>
        </div>
        <label className="block space-y-1"><span>Finalidad</span><input className={fieldClass} value={purpose} onChange={(event) => setPurpose(event.target.value)} placeholder="Por ejemplo: apoyo familiar" /></label>
        <details className="rounded-lg border border-[var(--color-hairline)] p-3">
          <summary className="cursor-pointer font-semibold">Datos bancarios opcionales</summary>
          <p className="mt-2 text-sm">Los requisitos dependen del banco y del método. Pide al destinatario los datos para recibir desde el extranjero: una cuenta local o una clave Pix no siempre acepta transferencias internacionales.</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="space-y-1"><span>Banco o proveedor</span><input className={fieldClass} value={bankName} autoComplete="off" onChange={(event) => setBankName(event.target.value)} /></label>
            <label className="space-y-1"><span>Agencia o sucursal</span><input className={fieldClass} value={branch} autoComplete="off" onChange={(event) => setBranch(event.target.value)} /></label>
            <label className="space-y-1"><span>Cuenta de destino</span><input className={fieldClass} value={account} autoComplete="off" onChange={(event) => setAccount(event.target.value)} /></label>
            <label className="space-y-1"><span>Código bancario o SWIFT/BIC</span><input className={fieldClass} value={bankCode} autoComplete="off" onChange={(event) => setBankCode(event.target.value)} /></label>
            <label className="space-y-1"><span>Identificación del destinatario, si se solicita</span><input className={fieldClass} value={recipientId} autoComplete="off" onChange={(event) => setRecipientId(event.target.value)} /></label>
          </div>
          <p className="mt-3 text-sm">Los datos se mantienen en esta pantalla y se incluyen en el archivo que decidas descargar. El archivo es texto sin cifrar: guárdalo de forma privada.</p>
        </details>
        <button type="button" onClick={downloadDraft} className="rounded-lg bg-[var(--color-seiji)] px-4 py-2 font-semibold text-white">Descargar preparación</button>
        {notice && <p role="status">Borrador descargado. Estos datos no se guardan en la app.</p>}
      </Card>
      <Card as="section" className="space-y-3 p-5">
        <h3 className="text-lg font-bold">2. Enviar mediante una entidad financiera</h3>
        <p>Usa la aplicación o sucursal de tu banco o proveedor de transferencias. Comprueba el destinatario, las comisiones y el tipo de cambio antes de confirmar.</p>
        <p>Un envío programado o pendiente no demuestra que el dinero haya llegado. Comprueba el estado final en el canal oficial de la entidad y, cuando corresponda, en la cuenta receptora.</p>
        <p>El Banco Central de Brasil recomienda que el destinatario consulte antes con la entidad receptora los documentos y condiciones de la operación.</p>
        <a className="inline-block underline" href="https://www.bcb.gov.br/meubc/faqs/p/como-faco-para-enviar-recursos-para-o-exterior-ou-para-receber-recursos-do-exterior-em-moeda-estrangeira" target="_blank" rel="noreferrer">Información del Banco Central de Brasil</a>
      </Card>
      <Card as="section" className="space-y-3 p-5">
        <h3 className="text-lg font-bold">3. Conservar y comprobar el documento</h3>
        <ul className="list-disc space-y-2 pl-5">
          <li>Descarga el comprobante original desde el banco o proveedor; contrasta fecha, importe, remitente, destinatario y número de operación con el historial oficial.</li>
          <li>Consulta al banco por sus canales oficiales si necesitas confirmar autenticidad o una operación concreta. Una imagen, un código o el OCR por sí solos no prueban que el pago sea auténtico.</li>
          <li>El destinatario debe comprobar el abono en su propia cuenta mediante la app o el canal oficial de su banco. Una operación programada no confirma que el dinero haya llegado.</li>
          <li>En Brasil, el titular puede consultar su informe de cambio y transferencias internacionales en Registrato. El Banco Central indica que las entidades pueden informar los datos hasta 44 días después de la liquidación: que todavía no aparezca no demuestra que sea falso. Consulta la operación concreta con la entidad responsable.</li>
          <li>Para familiares residentes fuera de Japón, la Agencia Tributaria pide documentación del parentesco y de remesas; los documentos en otro idioma necesitan traducción japonesa cuando corresponda.</li>
        </ul>
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={() => navigate("capture")} className="rounded-lg bg-[var(--color-seiji)] px-4 py-2 font-semibold text-white">Abrir captura y OCR</button>
          <button type="button" onClick={() => navigate("evidence")} className="rounded-lg border border-[var(--color-hairline)] px-4 py-2 font-semibold">Abrir documentos guardados</button>
        </div>
        <p className="text-sm text-[var(--color-sumi-soft)]">El OCR existente está orientado a recibos y no verifica remesas bancarias. Comprueba cualquier dato extraído con el documento original antes de aceptarlo.</p>
        <a className="inline-block underline" href="https://www.nta.go.jp/publication/pamph/pdf/0022009-107_02.pdf" target="_blank" rel="noreferrer">Requisitos oficiales de 国税庁</a>
        <a className="block underline" href="https://www.bcb.gov.br/meubc/faqs/s/relatorio-de-cambio-e-transferencias-internacionais" target="_blank" rel="noreferrer">Informe de transferencias del Banco Central de Brasil</a>
      </Card>
      <Card as="section" className="space-y-3 p-5">
        <h3 className="text-lg font-bold">4. Leer un comprobante real</h3>
        <p>Selecciona un PDF, PNG o JPEG de hasta 10 MB. El archivo se envía al servidor de tu app para leerlo temporalmente; puede utilizar almacenamiento temporal del servidor, pero no se añade a tus documentos ni se envía a un proveedor OCR externo. Las imágenes requieren un motor OCR local disponible en el servidor.</p>
        <p>El texto puede contener errores, repetirse o faltar información; en páginas con imágenes grandes se intenta OCR además de leer el texto seleccionable. No verifica autenticidad, identidad ni pago: contrástalo con el documento y el historial oficial del banco.</p>
        <label className="block space-y-1"><span>Archivo del comprobante</span><input type="file" disabled={reading} accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setExtracted(""); setWarnings([]); setEmptyPages([]); setReadError(""); setTextDownloaded(false); }} /></label>
        <label className="block space-y-1"><span>Idioma principal del documento escaneado</span><select className={fieldClass} value={language} disabled={reading} onChange={(event) => setLanguage(event.target.value)}><option value="pt">Portugués</option><option value="japan">Japonés</option></select></label>
        <button type="button" disabled={!file || reading} onClick={() => void readDocument()} className="rounded-lg bg-[var(--color-seiji)] px-4 py-2 font-semibold text-white disabled:opacity-50">{reading ? "Leyendo…" : "Leer documento"}</button>
        {readError && <p role="alert">{readError}</p>}
        {warnings.includes("ocr_unavailable") && <p role="status">El OCR local no está disponible para este idioma: las imágenes o páginas escaneadas no se pudieron leer.</p>}
        {warnings.includes("ocr_language_fallback") && <p role="status">Para el portugués se utilizó el reconocedor de español de Windows. La lectura es aproximada: revisa especialmente nombres y cifras.</p>}
        {warnings.includes("ocr_failed") && <p role="status">Falló el OCR local en al menos una página. Revisa el documento original.</p>}
        {warnings.includes("page_too_large") && <p role="status">Se omitió una página demasiado grande para procesarla.</p>}
        {warnings.includes("text_truncated") && <p role="status">El texto se recortó por superar el límite de visualización.</p>}
        {warnings.includes("no_text") && <p role="status">No se encontró texto legible.</p>}
        {emptyPages.length > 0 && <p role="status">No se extrajo texto de las páginas {emptyPages.join(", ")}. Pueden estar vacías o contener información que el OCR no pudo leer; revisa el original.</p>}
        {extracted && <div className="space-y-3">
          <label className="block space-y-1"><span>Texto extraído para revisar y corregir</span><textarea className={`${fieldClass} min-h-60`} value={extracted} onChange={(event) => { setExtracted(event.target.value); setTextDownloaded(false); }} /></label>
          <p className="text-sm">Compara nombres, fechas, importes y número de operación con el original. Este texto es editable y no sustituye al comprobante del banco.</p>
          <button type="button" onClick={downloadExtractedText} className="rounded-lg border border-[var(--color-hairline)] px-4 py-2 font-semibold">Descargar texto para revisión</button>
          {textDownloaded && <p role="status">Texto descargado sin cifrar. Guárdalo de forma privada junto al comprobante original.</p>}
        </div>}
      </Card>
    </main>
  );
}
