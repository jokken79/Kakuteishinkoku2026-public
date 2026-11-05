/**
 * 扶養家族 (dependientes) — 扶養控除 detallado + 国外居住 (research 08).
 *
 * El owner agrega cada familiar a cargo (nombre, fecha de nacimiento, parentesco,
 * ingreso, ¿vive con vos? 同居/別居, ¿dónde vive? Japón/extranjero+país). La app
 * **calcula sola la categoría y el monto** (一般/特定/老人/同居老親/年少/対象外) llamando
 * a `POST /dependents/classify`, y si el familiar vive en el extranjero muestra el
 * **checklist de documentos** requeridos (親族関係書類 + 送金関係書類 + ⚠️ traducción).
 *
 * La lista se persiste como UNA 控除 de tipo `fuyo` con `meta.dependents` (la lista
 * estructurada) y `amount` = Σ 扶養控除 (所得税). Al cambiar la lista, el impuesto del
 * 確定申告 se recalcula (mismo motor `/filing/draft`).
 */
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  classifyDependents,
  type Cohabitation,
  type DependentClassification,
  type DependentInput,
  type OverseasExemptionReason,
  type Residence,
} from "../lib/api";
import {
  useCreateDeduction,
  useDeductions,
  useDeleteDeduction,
  usePatchDeduction,
} from "../lib/hooks";
import { useActiveYear } from "../lib/hooks";
import { formatYen } from "../lib/format";
import { Card, Label } from "./ui";
import { Icon } from "./Icon";
import { HelpTerm } from "./HelpTerm";
import { stepBodyVariants } from "../variants/deductionVariants";

/** Una fila editable de dependiente en el formulario (estado local). */
interface DependentDraft extends DependentInput {
  /** Id local para keys de React (no se persiste). */
  _id: string;
}

const newDraft = (): DependentDraft => ({
  _id: crypto.randomUUID(),
  name: "",
  relationship: "",
  birth_date: "",
  goukei_shotoku: null,
  residence: "domestic",
  country: "",
  cohabitation: "together",
  eligible_cohabiting_ancestor: null,
  overseas_exemption: null,
  annual_remittance: null,
});

/** Normaliza un draft a `DependentInput` para enviar al backend. */
function toInput(d: DependentDraft): DependentInput {
  return {
    name: d.name || "（無名）",
    relationship: d.relationship || null,
    birth_date: d.birth_date || null,
    goukei_shotoku: d.goukei_shotoku ?? null,
    residence: d.residence,
    country: d.residence === "overseas" ? d.country || null : null,
    cohabitation: d.cohabitation,
    eligible_cohabiting_ancestor: d.cohabitation === "together"
      ? d.eligible_cohabiting_ancestor ?? null : null,
    overseas_exemption:
      d.residence === "overseas" ? d.overseas_exemption ?? null : null,
    annual_remittance: d.residence === "overseas" && d.overseas_exemption === "remittance_380k"
      ? d.annual_remittance ?? null : null,
  };
}

export function DependentsManager({ readOnly = false }: { readOnly?: boolean }) {
  const activeYear = useActiveYear();
  return <DependentsForYear key={activeYear} activeYear={activeYear} readOnly={readOnly} />;
}

function DependentsForYear({ activeYear, readOnly }: { activeYear: number; readOnly: boolean }) {
  const { data: list, isError: loadError } = useDeductions(activeYear);
  const create = useCreateDeduction(activeYear);
  const patch = usePatchDeduction(activeYear);
  const remove = useDeleteDeduction(activeYear);
  const yearLoaded = list?.year === activeYear;

  // Fila `fuyo` persistida (si existe) -> hidrata el estado local.
  const fuyoRow = yearLoaded ? list.deductions.find((d) => d.type === "fuyo") : undefined;
  const isLegacy = Boolean(fuyoRow && !Array.isArray(fuyoRow.meta?.dependents));
  const [replaceLegacy, setReplaceLegacy] = useState(false);
  const legacyLocked = isLegacy && !replaceLegacy;

  const [drafts, setDrafts] = useState<DependentDraft[]>([]);
  const [classificationResult, setClassificationResult] = useState<{
    key: string; items: DependentClassification[];
  } | null>(null);
  const [classificationError, setClassificationError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const hydrated = useRef(false);
  const classificationKey = JSON.stringify([activeYear, drafts.map(toInput)]);

  // Hidratar desde la fila persistida la primera vez que llega.
  useEffect(() => {
    if (hydrated.current || !yearLoaded) return;
    const stored = (fuyoRow?.meta?.dependents as DependentInput[] | undefined) ?? [];
    if (stored.length > 0) {
      setDrafts(
        stored.map((d) => ({
          _id: crypto.randomUUID(),
          name: d.name ?? "",
          relationship: d.relationship ?? "",
          birth_date: d.birth_date ?? "",
          goukei_shotoku: d.goukei_shotoku ?? null,
          residence: d.residence ?? "domestic",
          country: d.country ?? "",
          cohabitation: d.cohabitation ?? "together",
          eligible_cohabiting_ancestor: d.eligible_cohabiting_ancestor ?? null,
          overseas_exemption: d.overseas_exemption ?? null,
          annual_remittance: d.annual_remittance ?? null,
        })),
      );
      hydrated.current = true;
    } else if (fuyoRow !== undefined || list !== undefined) {
      hydrated.current = true;
    }
  }, [fuyoRow, list, yearLoaded]);

  // Reclasificar EN VIVO cada vez que cambian los drafts (la app calcula sola).
  useEffect(() => {
    let cancelled = false;
    if (drafts.length === 0) {
      return;
    }
    setClassificationError(null);
    classifyDependents(activeYear, drafts.map(toInput))
      .then((res) => {
        if (!cancelled && res.dependents.length === drafts.length) {
          setClassificationResult({ key: classificationKey, items: res.dependents });
        } else if (!cancelled) {
          setClassificationError(classificationKey);
        }
      })
      .catch(() => {
        if (!cancelled) setClassificationError(classificationKey);
      });
    return () => {
      cancelled = true;
    };
  }, [drafts, activeYear, classificationKey, retry]);

  const classificationReady = drafts.length === 0 || classificationResult?.key === classificationKey;
  const classifications = drafts.length > 0 && classificationReady ? classificationResult?.items ?? [] : [];

  const totalDeduction = classifications.reduce(
    (sum, c) => sum + c.income_tax_amount,
    0,
  );

  const addDependent = () => {
    if (readOnly || !yearLoaded || legacyLocked) return;
    setDrafts((prev) => [...prev, newDraft()]);
  };

  const updateDraft = (id: string, patchDraft: Partial<DependentDraft>) => {
    if (readOnly) return;
    setDrafts((prev) =>
      prev.map((d) => (d._id === id ? { ...d, ...patchDraft } : d)),
    );
  };

  const removeDraft = (id: string) => {
    if (readOnly) return;
    setDrafts((prev) => prev.filter((d) => d._id !== id));
  };

  // Persistir la lista como fila `fuyo` (meta.dependents + amount = Σ控除).
  const persist = () => {
    if (readOnly || !yearLoaded || !classificationReady || legacyLocked) return;
    if (isLegacy && drafts.length === 0) return;
    if (fuyoRow && !window.confirm(isLegacy
      ? "Se reemplazará el registro antiguo por esta lista. Haz una copia de seguridad antes de continuar. ¿Reemplazarlo?"
      : "Se actualizarán los familiares registrados. Haz una copia de seguridad antes de continuar. ¿Guardar los cambios?")) return;
    const meta = {
      year: activeYear,
      dependents: drafts.map(toInput),
    };
    if (drafts.length === 0) {
      if (fuyoRow) remove.mutate(fuyoRow.id);
      return;
    }
    if (fuyoRow) {
      patch.mutate({ id: fuyoRow.id, patch: { amount: totalDeduction, meta } });
    } else {
      create.mutate({ type: "fuyo", amount: totalDeduction, meta });
    }
  };

  const pending = create.isPending || patch.isPending || remove.isPending;

  return (
    <section className="mt-8">
      <div className="mb-3 flex items-center gap-2">
        <Icon name="home" className="h-4 w-4 text-[var(--color-sumi-soft)]" />
        <Label>扶養家族（扶養控除）</Label>
        <HelpTerm term="扶養控除" />
      </div>

      <Card className="p-5">
        {!yearLoaded && <p role={loadError ? "alert" : "status"} className="mb-3 text-sm">{loadError ? `No se pudieron cargar los familiares de ${activeYear}. Revisa la conexión antes de editar.` : `Cargando los datos de ${activeYear}…`}</p>}
        {isLegacy && <div role="alert" className="mb-4 rounded-lg border border-[var(--color-kohaku)] p-3 text-sm">
          <p>Existe una deducción de familiares en formato antiguo ({formatYen(fuyoRow?.amount)}). Este editor no puede recuperar los datos personales de esa lista.</p>
          <p className="mt-1">Para sustituirla, primero haz una copia de seguridad y vuelve a introducir todos los familiares. La sustitución se confirma al guardar.</p>
          {!replaceLegacy && <button type="button" disabled={readOnly} onClick={() => setReplaceLegacy(true)} className="mt-2 underline disabled:opacity-50">Preparar sustitución del registro antiguo</button>}
        </div>}
        <p className="text-sm leading-relaxed text-[var(--color-sumi)]">
          扶養している家族を追加すると、<span className="font-medium">年齢・続柄・所得・居住地</span>
          から区分と控除額をアプリが自動で判定します。海外（国外居住）の場合は、必要な書類も表示します。
        </p>
        <p className="mt-2 text-sm text-[var(--color-sumi-soft)]">Para estimar la deducción, introduce la fecha de nacimiento y el ingreso fiscal. Un campo vacío significa desconocido; escribe 0 solo si está confirmado.</p>
        <p className="mt-1 text-sm text-[var(--color-sumi-soft)]">Ejercicio {activeYear}. Guarda los cambios antes de cambiar de año: los datos no guardados se descartan.</p>

        <div className="mt-4 space-y-3">
          {drafts.map((draft, i) => (
            <DependentRow
              key={draft._id}
              draft={draft}
              classification={classifications[i]}
              readOnly={readOnly}
              onChange={(p) => updateDraft(draft._id, p)}
              onRemove={() => removeDraft(draft._id)}
            />
          ))}
        </div>

        <button
          type="button"
          onClick={addDependent}
          disabled={readOnly || !yearLoaded || legacyLocked}
          className="mt-4 flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-dashed border-[var(--color-hairline)] px-4 py-2.5 text-sm font-medium text-[var(--color-sumi-soft)] transition-colors hover:border-[var(--color-seiji)] hover:text-[var(--color-seiji)]"
        >
          <Icon name="check" className="h-4 w-4" />＋ 扶養家族を追加
        </button>

        {(drafts.length > 0 || (fuyoRow && !isLegacy)) && (
          <div className="mt-5 border-t border-[var(--color-hairline)] pt-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-[var(--color-sumi)]">
                扶養控除の合計（所得税）
              </span>
              <span className="tabular text-lg font-bold text-[var(--color-seiji)]">
                {classificationReady ? formatYen(totalDeduction) : "—"}
              </span>
            </div>
            <button
              type="button"
              onClick={persist}
              disabled={readOnly || pending || !yearLoaded || !classificationReady}
              className="mt-4 flex items-center gap-1.5 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              <Icon name="check" className="h-4 w-4" />
              {pending ? "保存中…" : "扶養家族を保存"}
            </button>
            {!classificationReady && (classificationError === classificationKey
              ? <p role="alert" className="mt-2 text-sm">No se pudo calcular la clasificación. <button type="button" className="underline" onClick={() => setRetry((value) => value + 1)}>Reintentar</button></p>
              : <p role="status" className="mt-2 text-sm">Calculando la clasificación de los datos actuales…</p>)}
          </div>
        )}
      </Card>
    </section>
  );
}

// --- Fila de un dependiente ------------------------------------------------

function DependentRow({
  draft,
  classification,
  readOnly,
  onChange,
  onRemove,
}: {
  draft: DependentDraft;
  classification: DependentClassification | undefined;
  readOnly: boolean;
  onChange: (patch: Partial<DependentDraft>) => void;
  onRemove: () => void;
}) {
  const isOverseas = draft.residence === "overseas";

  return (
    <div className="rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-paper-sink)]/40 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="氏名">
          <input
            type="text"
            value={draft.name}
            disabled={readOnly}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="例：架空 花子"
            className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-sumi)] outline-none focus:border-[var(--color-seiji)]"
          />
        </Field>
        <Field label="続柄">
          <input
            type="text"
            value={draft.relationship ?? ""}
            disabled={readOnly}
            onChange={(e) => onChange({ relationship: e.target.value })}
            placeholder="例：母"
            className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-sumi)] outline-none focus:border-[var(--color-seiji)]"
          />
        </Field>
        <Field label="生年月日">
          <input
            type="date"
            value={draft.birth_date ?? ""}
            disabled={readOnly}
            onChange={(e) => onChange({ birth_date: e.target.value })}
            className="tabular w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-sumi)] outline-none focus:border-[var(--color-seiji)]"
          />
        </Field>
        <Field label="その方の合計所得金額（年）">
          <div className="flex items-center rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] pl-3 focus-within:border-[var(--color-seiji)]">
            <span className="tabular text-sm text-[var(--color-sumi-soft)]">¥</span>
            <input
              type="text"
              inputMode="numeric"
              value={draft.goukei_shotoku == null ? "" : String(draft.goukei_shotoku)}
              disabled={readOnly}
              onChange={(e) =>
                onChange({
                  goukei_shotoku: e.target.value.replace(/[^0-9]/g, "") === "" ? null : Number(e.target.value.replace(/[^0-9]/g, "")),
                })
              }
              placeholder="例：0"
              className="tabular w-full bg-transparent px-2 py-2 text-right text-sm text-[var(--color-sumi)] outline-none"
            />
          </div>
        </Field>
      </div>

      {/* 同居/別居 + 居住地 */}
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="一緒に住んでいますか？">
          <Segmented
            value={draft.cohabitation ?? "together"}
            options={[
              { value: "together", label: "同居" },
              { value: "separate", label: "別居" },
            ]}
            onChange={(v) => onChange({ cohabitation: v as Cohabitation })}
            disabled={readOnly}
          />
        </Field>
        <Field label="お住まいは？">
          <Segmented
            value={draft.residence ?? "domestic"}
            options={[
              { value: "domestic", label: "日本国内" },
              { value: "overseas", label: "国外（海外）" },
            ]}
            onChange={(v) =>
              onChange({ residence: v as Residence })
            }
            disabled={readOnly}
          />
        </Field>
      </div>

      {draft.cohabitation === "together" && <label className="mt-3 block text-sm">
        <span>Para un familiar de 70 años o más: ¿cumple los requisitos de 同居老親等?</span>
        <select value={draft.eligible_cohabiting_ancestor == null ? "" : String(draft.eligible_cohabiting_ancestor)}
          disabled={readOnly} onChange={(event) => onChange({ eligible_cohabiting_ancestor: event.target.value === "" ? null : event.target.value === "true" })}
          className="mt-1 w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2">
          <option value="">Sin confirmar</option><option value="true">Sí, cumple los requisitos</option><option value="false">No</option>
        </select>
        <span className="mt-1 block text-xs">Debe ser ascendiente directo tuyo o de tu cónyuge y cumplir la convivencia habitual exigida. Mientras no se confirme, la estimación usa la categoría general de familiar mayor.</span>
      </label>}

      {/* 国外: país + motivo (30-69) */}
      <AnimatePresence initial={false}>
        {isOverseas && (
          <motion.div
            variants={stepBodyVariants}
            initial="collapsed"
            animate="expanded"
            exit="collapsed"
            className="overflow-hidden"
          >
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="居住国">
                <input
                  type="text"
                  value={draft.country ?? ""}
                  disabled={readOnly}
                  onChange={(e) => onChange({ country: e.target.value })}
                  placeholder="例：ペルー"
                  className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-sumi)] outline-none focus:border-[var(--color-seiji)]"
                />
              </Field>
              <Field label="30〜69歳の例外事由（あれば）">
                <select
                  value={draft.overseas_exemption ?? ""}
                  disabled={readOnly}
                  onChange={(e) =>
                    onChange({
                      overseas_exemption:
                        (e.target.value || null) as OverseasExemptionReason | null,
                    })
                  }
                  className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-sumi)] outline-none focus:border-[var(--color-seiji)]"
                >
                  <option value="">なし</option>
                  <option value="study">留学</option>
                  <option value="disability">障害者</option>
                  <option value="remittance_380k">送金38万円以上</option>
                </select>
              </Field>
            </div>
            {draft.overseas_exemption === "remittance_380k" && <label className="mt-3 block text-sm">
              <span>Envíos de este año a este familiar (¥)</span>
              <input type="number" min="0" step="1" value={draft.annual_remittance ?? ""} disabled={readOnly}
                onChange={(event) => onChange({ annual_remittance: event.target.value === "" ? null : Number(event.target.value) })}
                className="mt-1 w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2" />
              <span className="mt-1 block text-xs">Introduce solo importes reales para manutención o educación y conserva los comprobantes. La app no verifica las transferencias.</span>
            </label>}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Resultado en vivo: categoría + monto, o motivo de no-elegibilidad */}
      {classification && (
        <ClassificationResult c={classification} />
      )}

      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={onRemove}
          disabled={readOnly}
          className="rounded-[var(--radius-pill)] px-3 py-1.5 text-xs font-medium text-[var(--color-sumi-soft)] transition-colors hover:text-[var(--color-shuiro)]"
        >
          この家族を削除
        </button>
      </div>
    </div>
  );
}

// --- Resultado de la clasificación (en vivo) -------------------------------

function ClassificationResult({ c }: { c: DependentClassification }) {
  if (!c.qualifies && c.disqualified_message) {
    return (
      <div className="mt-3 flex items-start gap-2 rounded-lg bg-[var(--color-shuiro-soft,#fde8e8)] px-3 py-2.5">
        <Icon name="shield" className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-shuiro)]" />
        <span className="text-xs leading-relaxed text-[var(--color-sumi)]">
          <span className="font-semibold">{c.kind_label}：</span>
          {c.disqualified_message}
        </span>
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-lg bg-[var(--color-seiji-soft)] px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-[var(--color-seiji)]">
          <Icon name="check" className="h-4 w-4" />
          {c.kind_label}
          {c.age != null && (
            <span className="tabular text-xs font-normal text-[var(--color-sumi-soft)]">
              （{c.age}歳）
            </span>
          )}
        </span>
        <span className="tabular text-sm font-bold text-[var(--color-seiji)]">
          {c.income_tax_amount > 0
            ? `控除 ${formatYen(c.income_tax_amount)}`
            : "控除なし（登録のみ）"}
        </span>
      </div>
      {c.income_tax_amount > 0 && (
        <p className="tabular mt-1 text-[11px] text-[var(--color-sumi-soft)]">
          住民税の控除額：{formatYen(c.resident_tax_amount)}
        </p>
      )}

      {/* Checklist de documentos (国外居住) */}
      {c.is_overseas && c.required_documents.length > 0 && (
        <div className="mt-3 border-t border-[var(--color-seiji)]/20 pt-2.5">
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-[var(--color-sumi)]">
            <Icon name="file" className="h-3.5 w-3.5" />
            国外居住の必要書類
          </p>
          <ul className="space-y-1.5">
            {c.required_documents.map((doc) => (
              <li key={doc.code} className="flex items-start gap-2 text-xs">
                <span className="mt-0.5 inline-block h-3.5 w-3.5 shrink-0 rounded-[3px] border border-[var(--color-sumi-soft)]" />
                <span className="leading-relaxed text-[var(--color-sumi)]">
                  <span className="inline-flex items-center font-medium">
                    {doc.label}
                    <HelpTerm term={doc.label} />
                  </span>
                  <span className="block text-[var(--color-sumi-soft)]">
                    {doc.description}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          {c.needs_translation && (
            <p className="mt-2 flex items-start gap-1.5 rounded-md bg-[var(--color-kohaku-soft)] px-2.5 py-2 text-[11px] leading-relaxed text-[var(--color-sumi)]">
              <Icon name="bolt" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-kohaku)]" />
              <span>
                <span className="font-semibold">⚠️ 日本語の翻訳文が必要です。</span>
                スペイン語などの書類は、日本語訳を添付してください。
              </span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// --- Primitivos de formulario ----------------------------------------------

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--color-sumi-soft)]">
        {label}
      </span>
      {children}
    </label>
  );
}

function Segmented({
  value,
  options,
  onChange,
  disabled = false,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex gap-1 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] p-1">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          disabled={disabled}
          onClick={() => onChange(opt.value)}
          className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            value === opt.value
              ? "bg-[var(--color-sumi)] text-white"
              : "text-[var(--color-sumi-soft)] hover:bg-[var(--color-paper-sink)]"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
