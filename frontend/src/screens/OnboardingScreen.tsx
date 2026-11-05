/**
 * Onboarding guiado de primera vez (確定申告 2026).
 *
 * Se muestra cuando `onboarded=false` (usuario nuevo): en vez de arrancar en el
 * dashboard con datos de demo, lleva al usuario paso a paso (estilo freee
 * "質問に答えるだけ") a configurar SU perfil. Diseno "Calma fiscal": un paso a la
 * vez, japones primario + ayuda ES, barra de progreso, mobile-first, animacion
 * suave (respeta reduced-motion via MotionConfig global).
 *
 * Pasos:
 *   1. welcome       — bienvenida + que hace la app.
 *   2. help          — activar la ayuda en castellano (default ON).
 *   3. filing-type   — 青色申告 (65/55/10) vs 白色申告.
 *   4. consumption   — 課税事業者 vs 免税事業者 (default 免税).
 *   5. office        — 税務署 (提出先) (default 津島).
 *   6. profile       — 氏名/フリガナ/納税地/生年月日/職業/個人番号 (opcional).
 *   7. income        — 売上 + (opcional) 給与 + 源泉徴収.
 *   8. done          — resumen + 完了 -> POST /onboarding/complete.
 *
 * Al completar, el contenedor (App) detecta `onboarded=true` y entra al
 * dashboard con el perfil cargado.
 */
import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { FilingType } from "../lib/incomeFiling";
import {
  FILING_TYPE_OPTIONS,
  OFFICE_OPTIONS,
} from "../lib/incomeFiling";
import type { OnboardingComplete, OnboardingIncome } from "../lib/api";
import { useActiveYear, useCompleteOnboarding, useOnboardingStatus } from "../lib/hooks";
import { useUiStore } from "../lib/store";
import { Icon, type IconName } from "../components/Icon";
import { HelpToggle, HelpSubtitle } from "../components/HelpTerm";
import {
  onboardingOverlayVariants,
  onboardingStepVariants,
  onboardingOptionVariants,
} from "../variants/onboardingVariants";

/** Ids de los pasos, en orden. */
const STEP_IDS = [
  "welcome",
  "help",
  "filing-type",
  "consumption",
  "office",
  "profile",
  "income",
  "done",
] as const;
type StepId = (typeof STEP_IDS)[number];

/** Estado mutable del formulario de onboarding. */
interface Draft {
  filingType: FilingType | null;
  isTaxable: boolean | null;
  filingOffice: string;
  name: string;
  nameKana: string;
  postalCode: string;
  address: string;
  birthDate: string;
  businessType: string;
  myNumber: string;
  salesRevenue: string;
  salaryGross: string;
  salaryWithholding: string;
}

const INITIAL_DRAFT: Draft = {
  filingType: null,
  isTaxable: null,
  filingOffice: "",
  name: "",
  nameKana: "",
  postalCode: "",
  address: "",
  birthDate: "",
  businessType: "",
  myNumber: "",
  salesRevenue: "",
  salaryGross: "",
  salaryWithholding: "",
};

export function OnboardingScreen() {
  const [stepIndex, setStepIndex] = useState(0);
  const [direction, setDirection] = useState(1);
  const [draft, setDraft] = useState<Draft>(INITIAL_DRAFT);
  const complete = useCompleteOnboarding();
  const onboardingStatus = useOnboardingStatus();
  const year = useActiveYear();
  const setActiveSection = useUiStore((s) => s.setActiveSection);

  const step: StepId = STEP_IDS[stepIndex];
  const isLast = stepIndex === STEP_IDS.length - 1;
  const total = STEP_IDS.length;

  const update = (patch: Partial<Draft>) =>
    setDraft((prev) => ({ ...prev, ...patch }));

  const goNext = () => {
    if (step === "filing-type" && !draft.filingType) return;
    if (step === "consumption" && draft.isTaxable === null) return;
    if (stepIndex < total - 1) {
      setDirection(1);
      setStepIndex((i) => i + 1);
    }
  };
  const goBack = () => {
    if (stepIndex > 0) {
      setDirection(-1);
      setStepIndex((i) => i - 1);
    }
  };

  const handleFinish = () => {
    if (!draft.filingType || draft.isTaxable === null) return;
    if (onboardingStatus.data?.has_taxpayer !== false && !window.confirm(
      `Este perfil puede contener datos anteriores. La modalidad se guardará para ${year}. El IVA y la oficina fiscal pertenecen al perfil general y pueden afectar otros ejercicios. También se pueden reemplazar ingresos existentes del mismo tipo. Haz una copia de seguridad y revisa todos los datos antes de continuar. ¿Confirmas que quieres guardar estos cambios?`,
    )) return;
    const incomes: OnboardingIncome[] = [];
    const sales = digits(draft.salesRevenue);
    if (hasAmount(draft.salesRevenue)) incomes.push({ income_type: "jigyo", gross: sales });
    const salaryGross = digits(draft.salaryGross);
    const salaryWh = digits(draft.salaryWithholding);
    if (hasAmount(draft.salaryGross) || hasAmount(draft.salaryWithholding)) {
      incomes.push({
        income_type: "kyuyo",
        ...(hasAmount(draft.salaryGross) ? { gross: salaryGross } : {}),
        ...(hasAmount(draft.salaryWithholding) ? { withholding: salaryWh } : {}),
      });
    }
    const payload: OnboardingComplete = {
      name: draft.name.trim() || undefined,
      name_kana: draft.nameKana.trim() || undefined,
      my_number: draft.myNumber.trim() || undefined,
      postal_code: draft.postalCode.trim() || undefined,
      address: draft.address.trim() || undefined,
      birth_date: draft.birthDate || undefined,
      business_type: draft.businessType.trim() || undefined,
      filing_type: draft.filingType,
      is_taxable_consumption: draft.isTaxable,
      filing_office: draft.filingOffice || undefined,
      incomes,
    };
    complete.mutate(payload, {
      onSuccess: () => {
        // Entrar al dashboard con el perfil recien cargado.
        setActiveSection("dashboard");
      },
    });
  };

  return (
    <motion.div
      variants={onboardingOverlayVariants}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="fixed inset-0 z-40 flex flex-col bg-[var(--color-paper)]"
      role="dialog"
      aria-modal="true"
      aria-label="初期設定（オンボーディング）"
    >
      {import.meta.env.VITE_DEMO_MODE === "true" && (
        <div className="bg-amber-100 px-3 py-2 text-center text-sm font-semibold text-amber-950" role="status">
          デモモード・架空データ / DEMOSTRACIÓN: datos ficticios; no son tu declaración real.
        </div>
      )}
      {/* Header: marca + progreso + ayuda ES */}
      <header className="flex items-center justify-between gap-3 border-b border-[var(--color-hairline)] px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2.5">
          <div
            className="grid h-7 w-7 place-items-center rounded-md border-[1.5px] border-[var(--color-sumi)] text-[12px] font-bold text-[var(--color-sumi)]"
            aria-hidden
          >
            申
          </div>
          <span className="text-[13px] font-semibold text-[var(--color-sumi)]">
            はじめての設定
          </span>
        </div>
        <HelpToggle variant="compact" />
      </header>

      {/* Barra de progreso */}
      <ProgressBar current={stepIndex} total={total} />

      {/* Cuerpo: un paso a la vez */}
      <div className="relative flex min-h-0 flex-1 items-start justify-center overflow-auto px-4 py-6 sm:py-10">
        <div className="w-full max-w-lg">
          <AnimatePresence mode="wait" custom={direction}>
            <motion.div
              key={step}
              custom={direction}
              variants={onboardingStepVariants}
              initial="enter"
              animate="center"
              exit="exit"
            >
              <StepContent
                step={step}
                draft={draft}
                update={update}
                pending={complete.isPending}
                error={complete.isError ? complete.error?.message : null}
              />
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {/* Footer: navegacion */}
      <footer className="border-t border-[var(--color-hairline)] px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-6">
        <div className="mx-auto flex w-full max-w-lg items-center justify-between gap-3">
          <button
            type="button"
            onClick={goBack}
            disabled={stepIndex === 0 || complete.isPending}
            className="rounded-[var(--radius-pill)] px-4 py-2.5 text-sm font-medium text-[var(--color-sumi-soft)] transition-colors hover:text-[var(--color-sumi)] disabled:invisible"
          >
            戻る
          </button>

          {isLast ? (
            <button
              type="button"
              onClick={handleFinish}
              disabled={complete.isPending}
              className="flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-shuiro)] px-6 py-2.5 text-sm font-semibold text-white shadow-[var(--shadow-paper)] transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              <Icon name="check" className="h-4 w-4" />
              {complete.isPending ? "保存中…" : "完了"}
            </button>
          ) : (
            <button
              type="button"
              onClick={goNext}
              disabled={(step === "filing-type" && !draft.filingType) || (step === "consumption" && draft.isTaxable === null)}
              className="flex items-center gap-1.5 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-6 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {stepIndex === 0 ? "はじめる" : "次へ"}
              <Icon name="arrow" className="h-4 w-4" />
            </button>
          )}
        </div>
      </footer>
    </motion.div>
  );
}

/** Barra de progreso serena (celadon que avanza). */
function ProgressBar({ current, total }: { current: number; total: number }) {
  const pct = Math.round(((current + 1) / total) * 100);
  return (
    <div className="px-4 pt-3 sm:px-6">
      <div className="mx-auto w-full max-w-lg">
        <div className="mb-1 flex items-center justify-between">
          <HelpSubtitle>Configuración paso a paso</HelpSubtitle>
          <span className="tabular text-[11px] font-medium text-[var(--color-sumi-soft)]">
            {current + 1} / {total}
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-paper-sink)]">
          <motion.div
            className="h-full rounded-full bg-[var(--color-seiji)]"
            initial={false}
            animate={{ width: `${pct}%` }}
            transition={{ type: "spring", stiffness: 200, damping: 30 }}
          />
        </div>
      </div>
    </div>
  );
}

// --- Contenido por paso ----------------------------------------------------

function StepContent({
  step,
  draft,
  update,
  pending,
  error,
}: {
  step: StepId;
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
  pending: boolean;
  error: string | null;
}) {
  switch (step) {
    case "welcome":
      return <WelcomeStep />;
    case "help":
      return <HelpStep />;
    case "filing-type":
      return <FilingTypeStep draft={draft} update={update} />;
    case "consumption":
      return <ConsumptionStep draft={draft} update={update} />;
    case "office":
      return <OfficeStep draft={draft} update={update} />;
    case "profile":
      return <ProfileStep draft={draft} update={update} />;
    case "income":
      return <IncomeStep draft={draft} update={update} />;
    case "done":
      return <DoneStep draft={draft} pending={pending} error={error} />;
  }
}

/** Encabezado comun de un paso (icono + titulo JP + subtitulo ES). */
function StepHeader({
  icon,
  title,
  es,
  lead,
}: {
  icon: IconName;
  title: string;
  es: string;
  lead?: string;
}) {
  return (
    <div className="mb-6 text-center">
      <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]">
        <Icon name={icon} className="h-7 w-7" />
      </div>
      <h2 className="text-xl font-bold text-[var(--color-sumi)]">{title}</h2>
      <HelpSubtitle className="mt-1 text-center text-xs">{es}</HelpSubtitle>
      {lead && (
        <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-[var(--color-sumi-soft)]">
          {lead}
        </p>
      )}
    </div>
  );
}

function WelcomeStep() {
  return (
    <div className="py-6 text-center">
      <motion.div
        variants={onboardingOptionVariants}
        initial="hidden"
        animate="visible"
        className="mx-auto mb-6 grid h-20 w-20 place-items-center rounded-3xl border-[1.5px] border-[var(--color-sumi)] text-3xl font-bold text-[var(--color-sumi)]"
      >
        申
      </motion.div>
      <h2 className="text-2xl font-bold tracking-tight text-[var(--color-sumi)]">
        確定申告を、かんたんに。
      </h2>
      <HelpSubtitle className="mt-2 text-center text-sm">
        La declaración de la renta, fácil.
      </HelpSubtitle>
      <p className="mx-auto mt-5 max-w-sm text-sm leading-relaxed text-[var(--color-sumi-soft)]">
        領収書を撮るだけで仕訳を作り、質問に答えるだけで申告書ができます。まずは、いくつかの質問であなたの設定をします。
      </p>
      <HelpSubtitle className="mx-auto mt-3 max-w-sm text-center text-xs">
        Sacás una foto del recibo y la app arma el asiento; respondés unas
        preguntas y queda la declaración. Empecemos configurando tu perfil.
      </HelpSubtitle>

      <ul className="mx-auto mt-6 max-w-sm space-y-2.5 text-left">
        {[
          { icon: "camera" as IconName, t: "領収書を撮影", es: "Foto del recibo" },
          { icon: "compass" as IconName, t: "質問に答えるだけ", es: "Solo respondés" },
          { icon: "file" as IconName, t: "申告書を生成", es: "Genera la declaración" },
        ].map((row) => (
          <li
            key={row.t}
            className="flex items-center gap-3 rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-4 py-3"
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
              <Icon name={row.icon} className="h-4.5 w-4.5" />
            </span>
            <span>
              <span className="block text-sm font-medium text-[var(--color-sumi)]">
                {row.t}
              </span>
              <HelpSubtitle>{row.es}</HelpSubtitle>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function HelpStep() {
  return (
    <div>
      <StepHeader
        icon="sparkle"
        title="スペイン語の説明を表示しますか？"
        es="¿Mostrar la ayuda en español?"
        lead="画面は日本語のままで、税務用語にスペイン語の説明（?）と小さな字幕を付けられます。あとで「設定」からいつでも切り替えできます。"
      />
      <div className="rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] p-5">
        <HelpToggle variant="full" />
      </div>
      <p className="mt-4 text-center text-xs leading-relaxed text-[var(--color-sumi-soft)]">
        公式の申告内容は日本語です。スペイン語は理解のための補助です。
      </p>
    </div>
  );
}

function FilingTypeStep({
  draft,
  update,
}: {
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
}) {
  return (
    <div>
      <StepHeader
        icon="book"
        title="申告の種類を選んでください"
        es="Elegí el tipo de declaración"
        lead="申告区分と控除額は、承認・帳簿・提出方法などの要件を確認して選択してください。"
      />
      <p className="mb-4 text-sm leading-relaxed text-[var(--color-sumi)]">
        Elige una opción después de revisar sus requisitos. El máximo de 65万円 no es automático; consulta los libros y la forma y plazo de presentación.
        {" "}<a className="underline" href="https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/2072.htm" target="_blank" rel="noreferrer">Requisitos de 国税庁</a>
      </p>
      <div className="space-y-2.5">
        {FILING_TYPE_OPTIONS.map((opt) => {
          const active = draft.filingType === opt.value;
          return (
            <motion.button
              key={opt.value}
              type="button"
              variants={onboardingOptionVariants}
              initial="hidden"
              animate="visible"
              onClick={() => update({ filingType: opt.value })}
              aria-pressed={active}
              className={`flex w-full items-start gap-3 rounded-[var(--radius-card)] border px-4 py-3.5 text-left transition-colors ${
                active
                  ? "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)]"
                  : "border-[var(--color-hairline)] bg-[var(--color-surface)] hover:bg-[var(--color-paper-sink)]"
              }`}
            >
              <span
                className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border ${
                  active
                    ? "border-[var(--color-seiji)] bg-[var(--color-seiji)] text-white"
                    : "border-[var(--color-hairline)]"
                }`}
              >
                {active && <Icon name="check" className="h-3 w-3" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-[var(--color-sumi)]">
                    {opt.label}
                  </span>
                </span>
                <span className="mt-1 block text-xs leading-relaxed text-[var(--color-sumi-soft)]">
                  {opt.help}
                </span>
                <HelpSubtitle className="mt-1">{opt.es}</HelpSubtitle>
              </span>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}

function ConsumptionStep({
  draft,
  update,
}: {
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
}) {
  const OPTIONS = [
    {
      taxable: false,
      label: "免税事業者",
      es: "Exento de IVA (免税)",
      help: "基準期間・特定期間の売上やインボイス登録、届出などを確認してください。",
    },
    {
      taxable: true,
      label: "課税事業者",
      es: "Sujeto a IVA (課税)",
      help: "インボイス登録や課税事業者の選択、基準期間・特定期間などの条件を確認してください。",
    },
  ];
  return (
    <div>
      <StepHeader
        icon="box"
        title="消費税はどちらですか？"
        es="¿Sos sujeto o exento de IVA?"
        lead="基準期間・特定期間の課税売上、インボイス登録や届出などを確認して選んでください。"
      />
      <p className="mb-4 text-sm leading-relaxed text-[var(--color-sumi)]">
        Las ventas del año actual por sí solas no determinan la exención. Revisa también los períodos aplicables, el registro de インボイス y las comunicaciones presentadas. {" "}
        <a href="https://www.nta.go.jp/taxes/shiraberu/taxanswer/shohi/6501.htm" target="_blank" rel="noreferrer" className="underline">Consultar 国税庁</a>
      </p>
      <div className="space-y-2.5">
        {OPTIONS.map((opt) => {
          const active = draft.isTaxable === opt.taxable;
          return (
            <motion.button
              key={opt.label}
              type="button"
              variants={onboardingOptionVariants}
              initial="hidden"
              animate="visible"
              onClick={() => update({ isTaxable: opt.taxable })}
              aria-pressed={active}
              className={`flex w-full items-start gap-3 rounded-[var(--radius-card)] border px-4 py-3.5 text-left transition-colors ${
                active
                  ? "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)]"
                  : "border-[var(--color-hairline)] bg-[var(--color-surface)] hover:bg-[var(--color-paper-sink)]"
              }`}
            >
              <span
                className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border ${
                  active
                    ? "border-[var(--color-seiji)] bg-[var(--color-seiji)] text-white"
                    : "border-[var(--color-hairline)]"
                }`}
              >
                {active && <Icon name="check" className="h-3 w-3" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-[var(--color-sumi)]">
                    {opt.label}
                  </span>
                </span>
                <span className="mt-1 block text-xs leading-relaxed text-[var(--color-sumi-soft)]">
                  {opt.help}
                </span>
                <HelpSubtitle className="mt-1">{opt.es}</HelpSubtitle>
              </span>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}

function OfficeStep({
  draft,
  update,
}: {
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
}) {
  const known = OFFICE_OPTIONS.some((o) => o.value === draft.filingOffice);
  return (
    <div>
      <StepHeader
        icon="home"
        title="提出先の税務署を選んでください"
        es="Elegí tu oficina tributaria (税務署)"
        lead="申告書を提出する税務署です。お住まいの地域によって決まります。わからなければ、あとで「設定」から変更できます。"
      />
      <p className="mb-4 text-sm leading-relaxed text-[var(--color-sumi)]">
        Si no eliges una oficina, se conserva la ya registrada. La app solo tiene
        verificada 津島税務署; para otras oficinas revisa y completa el formulario oficial.
      </p>
      <div className="space-y-2.5">
        {OFFICE_OPTIONS.map((opt) => {
          const active = draft.filingOffice === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => update({ filingOffice: opt.value })}
              aria-pressed={active}
              className={`flex w-full items-center gap-3 rounded-[var(--radius-card)] border px-4 py-3.5 text-left transition-colors ${
                active
                  ? "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)]"
                  : "border-[var(--color-hairline)] bg-[var(--color-surface)] hover:bg-[var(--color-paper-sink)]"
              }`}
            >
              <span
                className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border ${
                  active
                    ? "border-[var(--color-seiji)] bg-[var(--color-seiji)] text-white"
                    : "border-[var(--color-hairline)]"
                }`}
              >
                {active && <Icon name="check" className="h-3 w-3" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-[var(--color-sumi)]">
                  {opt.label}
                </span>
                <span className="block text-xs text-[var(--color-sumi-soft)]">
                  {opt.note}
                </span>
              </span>
            </button>
          );
        })}

        {/* Input libre para otros 税務署 */}
        <div className="rounded-[var(--radius-card)] border border-dashed border-[var(--color-hairline)] bg-[var(--color-surface)] px-4 py-3.5">
          <label
            htmlFor="ob-office-other"
            className="mb-1.5 block text-xs font-medium text-[var(--color-sumi-soft)]"
          >
            その他の税務署（任意）
          </label>
          <input
            id="ob-office-other"
            type="text"
            placeholder="例：nagoya-naka"
            value={known ? "" : draft.filingOffice}
            onChange={(e) => update({ filingOffice: e.target.value })}
            className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-sumi)] focus:border-[var(--color-seiji)] focus:outline-none"
          />
          <HelpSubtitle className="mt-1">
            Si tu oficina no está en la lista, escribí su clave.
          </HelpSubtitle>
        </div>
      </div>
    </div>
  );
}

function ProfileStep({
  draft,
  update,
}: {
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
}) {
  return (
    <div>
      <StepHeader
        icon="edit"
        title="あなたの情報を入力してください"
        es="Tus datos personales"
        lead="申告書に記載される情報です。あとで「設定」から変更できます。個人番号は任意です。"
      />
      <div className="space-y-3">
        <TextField
          id="ob-name"
          label="氏名"
          es="Nombre"
          placeholder="例：山田 太郎"
          value={draft.name}
          onChange={(v) => update({ name: v })}
        />
        <TextField
          id="ob-kana"
          label="フリガナ"
          es="Lectura (katakana)"
          placeholder="例：ヤマダ タロウ"
          value={draft.nameKana}
          onChange={(v) => update({ nameKana: v })}
        />
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-1">
            <TextField
              id="ob-postal"
              label="郵便番号"
              es="Código postal"
              placeholder="例：100-0001"
              value={draft.postalCode}
              onChange={(v) => update({ postalCode: v })}
            />
          </div>
          <div className="col-span-2">
            <TextField
              id="ob-address"
              label="住所（納税地）"
              es="Domicilio fiscal"
              placeholder="例：東京都千代田区1-1"
              value={draft.address}
              onChange={(v) => update({ address: v })}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label htmlFor="ob-birth" className="block">
            <span className="mb-1 block text-xs font-medium text-[var(--color-sumi-soft)]">
              生年月日
            </span>
            <HelpSubtitle className="-mt-1 mb-1">Fecha de nacimiento</HelpSubtitle>
            <input
              id="ob-birth"
              type="date"
              value={draft.birthDate}
              onChange={(e) => update({ birthDate: e.target.value })}
              className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2.5 text-sm text-[var(--color-sumi)] focus:border-[var(--color-seiji)] focus:outline-none"
            />
          </label>
          <TextField
            id="ob-job"
            label="職業"
            es="Profesión"
            placeholder="例：デザイナー"
            value={draft.businessType}
            onChange={(v) => update({ businessType: v })}
          />
        </div>
        <MyNumberField
          value={draft.myNumber}
          onChange={(v) => update({ myNumber: v })}
        />
      </div>
    </div>
  );
}

function IncomeStep({
  draft,
  update,
}: {
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
}) {
  return (
    <div>
      <StepHeader
        icon="signal"
        title="今年の収入を入力してください"
        es="Tus ingresos de este año"
        lead="事業の売上を入力します。給与があれば、源泉徴収票の金額も入力できます。あとで「収入」画面から追加・編集できます。"
      />
      <div className="space-y-3">
        <AmountField
          id="ob-sales"
          label="事業の売上（年間）"
          es="Ventas del negocio (anual)"
          placeholder="例：6,800,000"
          value={draft.salesRevenue}
          onChange={(v) => update({ salesRevenue: v })}
        />

        <div className="rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)] p-4">
          <p className="mb-1 text-xs font-medium text-[var(--color-sumi-soft)]">
            給与収入（任意）
          </p>
          <HelpSubtitle className="mb-3">
            Salario (opcional) — si tuviste empleo
          </HelpSubtitle>
          <div className="space-y-3">
            <AmountField
              id="ob-salary"
              label="給与の収入金額"
              es="Importe del salario"
              placeholder="例：0"
              value={draft.salaryGross}
              onChange={(v) => update({ salaryGross: v })}
            />
            <AmountField
              id="ob-wh"
              label="源泉徴収税額（源泉徴収票から）"
              es="Retención en origen (源泉)"
              placeholder="例：0"
              value={draft.salaryWithholding}
              onChange={(v) => update({ salaryWithholding: v })}
            />
          </div>
        </div>
        <p className="text-center text-xs leading-relaxed text-[var(--color-sumi-soft)]">
          入力は任意です。空欄のままでも、あとから「収入」画面で登録できます。
        </p>
        <p className="text-center text-sm leading-relaxed text-[var(--color-sumi)]">
          Deja un campo vacío para conservar su valor anterior. Escribe 0 solo si quieres registrar cero.
        </p>
      </div>
    </div>
  );
}

function DoneStep({
  draft,
  pending,
  error,
}: {
  draft: Draft;
  pending: boolean;
  error: string | null;
}) {
  const filingLabel =
    FILING_TYPE_OPTIONS.find((o) => o.value === draft.filingType)?.label ??
    draft.filingType ?? "未選択";
  const officeLabel =
    OFFICE_OPTIONS.find((o) => o.value === draft.filingOffice)?.label ??
    (draft.filingOffice || "未設定");
  const sales = digits(draft.salesRevenue);

  return (
    <div>
      <StepHeader
        icon="check"
        title="設定の確認"
        es="Resumen de tu configuración"
        lead="この内容で設定します。「完了」を押すと、あなたの情報でダッシュボードが開きます。"
      />
      <dl className="divide-y divide-[var(--color-hairline)] overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-surface)]">
        <SummaryRow label="氏名" es="Nombre" value={draft.name || "未入力"} />
        <SummaryRow label="申告区分" es="Tipo" value={filingLabel} />
        <SummaryRow
          label="消費税"
          es="IVA"
          value={draft.isTaxable === null ? "未選択" : draft.isTaxable ? "課税事業者" : "免税事業者"}
        />
        <SummaryRow label="提出先" es="Oficina" value={officeLabel} />
        <SummaryRow
          label="事業の売上"
          es="Ventas"
          value={hasAmount(draft.salesRevenue) ? `¥${sales.toLocaleString("ja-JP")}` : "未入力"}
        />
      </dl>

      {pending && (
        <p className="mt-4 text-center text-sm text-[var(--color-sumi-soft)]">
          保存しています…
        </p>
      )}
      {error && (
        <div className="mt-4 rounded-[var(--radius-card)] bg-[var(--color-kohaku-soft)] px-4 py-3 text-center">
          <p className="text-sm text-[var(--color-sumi)]">{error}</p>
          <HelpSubtitle className="mt-1">
            Revisá la conexión y volvé a intentar con 完了.
          </HelpSubtitle>
        </div>
      )}
    </div>
  );
}

function SummaryRow({
  label,
  es,
  value,
}: {
  label: string;
  es: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3">
      <dt className="min-w-0">
        <span className="block text-xs font-medium text-[var(--color-sumi-soft)]">
          {label}
        </span>
        <HelpSubtitle>{es}</HelpSubtitle>
      </dt>
      <dd className="truncate text-sm font-semibold text-[var(--color-sumi)]">
        {value}
      </dd>
    </div>
  );
}

// --- Campos reutilizables --------------------------------------------------

function TextField({
  id,
  label,
  es,
  placeholder,
  value,
  onChange,
}: {
  id: string;
  label: string;
  es: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label htmlFor={id} className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--color-sumi-soft)]">
        {label}
      </span>
      <HelpSubtitle className="-mt-1 mb-1">{es}</HelpSubtitle>
      <input
        id={id}
        type="text"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2.5 text-sm text-[var(--color-sumi)] focus:border-[var(--color-seiji)] focus:outline-none placeholder:text-[var(--color-sumi-soft)]/50"
      />
    </label>
  );
}

function AmountField({
  id,
  label,
  es,
  placeholder,
  value,
  onChange,
}: {
  id: string;
  label: string;
  es: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label htmlFor={id} className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--color-sumi-soft)]">
        {label}
      </span>
      <HelpSubtitle className="-mt-1 mb-1">{es}</HelpSubtitle>
      <div className="flex items-center rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] pl-3.5 pr-3 focus-within:border-[var(--color-seiji)]">
        <span className="tabular mr-0.5 text-sm text-[var(--color-sumi-soft)]">¥</span>
        <input
          id={id}
          type="text"
          inputMode="numeric"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value.replace(/[^0-9,]/g, ""))}
          className="tabular w-full bg-transparent px-2 py-2.5 text-right text-sm text-[var(--color-sumi)] outline-none placeholder:text-[var(--color-sumi-soft)]/50"
        />
      </div>
    </label>
  );
}

/** Campo del 個人番号 (opcional, enmascarado salvo que se muestre). */
function MyNumberField({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const [show, setShow] = useState(false);
  const masked = useMemo(() => "•".repeat(value.length), [value.length]);
  return (
    <label htmlFor="ob-mynumber" className="block">
      <span className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium text-[var(--color-sumi-soft)]">
          個人番号（マイナンバー・任意）
        </span>
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          className="text-[11px] font-medium text-[var(--color-seiji)] hover:underline"
        >
          {show ? "隠す" : "表示"}
        </button>
      </span>
      <HelpSubtitle className="-mt-1 mb-1">
        Mi Número (opcional, sensible)
      </HelpSubtitle>
      <input
        id="ob-mynumber"
        type="text"
        inputMode="numeric"
        autoComplete="off"
        placeholder="例：1234 5678 9012"
        value={show ? value : masked}
        onChange={(e) => {
          // Solo aceptamos digitos al editar; en modo enmascarado no editamos.
          if (show) onChange(e.target.value.replace(/[^0-9]/g, "").slice(0, 12));
        }}
        readOnly={!show}
        className="tabular w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2.5 text-sm tracking-widest text-[var(--color-sumi)] focus:border-[var(--color-seiji)] focus:outline-none"
      />
    </label>
  );
}

/** Convierte un string de monto ("6,800,000") a numero (6800000). */
function digits(raw: string): number {
  return Number(raw.replaceAll(",", "")) || 0;
}

function hasAmount(raw: string): boolean {
  return /\d/.test(raw);
}
