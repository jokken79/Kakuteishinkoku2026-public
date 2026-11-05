/**
 * 提案・アドバイス — motor de recomendaciones fiscales (節税アドバイザー, plan 08).
 *
 * Analiza el estado fiscal REAL del owner (所得税 + 住民税 ya calculados + la
 * detección proactiva de 控除) y muestra una lista PRIORIZADA de recomendaciones
 * accionables, cada una con su AHORRO estimado en yenes (所得税 / 住民税 / total,
 * marcado 概算) y un botón-atajo que navega al screen que la resuelve.
 *
 * Persona "gentleman": el japonés es primario (documento oficial); la ayuda ES
 * explica el POR QUÉ. Nunca presiona: sugiere con el número de ahorro a la vista.
 * Los números NO se inventan ni se hardcodean — salen del backend, que recalcula
 * cada escenario "qué pasaría si" con el mismo motor fiscal.
 */
import { motion } from "framer-motion";
import type {
  Recommendation,
  RecommendationCategory,
  RecommendationPriority,
  RecommendationStatus,
} from "../lib/api";
import { useRecommendations } from "../lib/hooks";
import { useUiStore } from "../lib/store";
import { formatYen } from "../lib/format";
import { Card, ErrorState, Label, Skeleton } from "../components/ui";
import { Icon, type IconName } from "../components/Icon";
import { HelpSubtitle } from "../components/HelpTerm";
import { screenVariants, staggerContainer } from "../variants/layoutVariants";
import {
  recommendationCardVariants,
  savingAmountVariants,
} from "../variants/recommendationsVariants";

// --- Metadatos visuales por prioridad / categoría / estado -----------------

const PRIORITY_META: Record<
  RecommendationPriority,
  { label: string; es: string; className: string }
> = {
  alta: {
    label: "優先度 高",
    es: "Prioridad alta",
    className:
      "border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] text-[var(--color-kohaku)]",
  },
  media: {
    label: "優先度 中",
    es: "Prioridad media",
    className:
      "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]",
  },
  baja: {
    label: "優先度 低",
    es: "Prioridad baja",
    className:
      "border-[var(--color-hairline)] bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]",
  },
};

const CATEGORY_ICON: Record<RecommendationCategory, IconName> = {
  setsuzei: "sparkle",
  kosei: "compass",
  info: "check",
};

const STATUS_META: Record<RecommendationStatus, { label: string; es: string }> = {
  actionable: { label: "確認候補", es: "Revisar condiciones" },
  applied: { label: "適用済み", es: "Ya aplicado" },
  needs_info: { label: "要入力", es: "Falta un dato" },
};

// --- Pantalla --------------------------------------------------------------

export function RecommendationsScreen() {
  const { data, isLoading, isError, refetch } = useRecommendations();

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-2xl px-4 py-6 pb-24 sm:px-8 sm:py-10"
    >
      {/* Encabezado */}
      <div className="mb-5">
        <h2 className="text-xl font-bold text-[var(--color-sumi)]">提案・アドバイス</h2>
        <HelpSubtitle className="mt-1">
          Ideas basadas en los datos registrados y, en algunos casos, escenarios hipotéticos.
          Revisa los requisitos antes de aplicarlas.
        </HelpSubtitle>
      </div>

      {isLoading ? (
        <LoadingSkeletons />
      ) : isError ? (
        <ErrorState
          message="提案を読み込めませんでした。もう一度お試しください。"
          onRetry={() => void refetch()}
        />
      ) : !data || data.recommendations.length === 0 ? (
        <EmptyAdvice />
      ) : (
        <>
          <SavingHero count={data.actionable_count} />

          <section className="mt-7">
            <div className="mb-3 flex items-center gap-2">
              <Icon name="sparkle" className="h-4 w-4 text-[var(--color-seiji)]" />
              <Label>あなたへのおすすめ</Label>
              <HelpSubtitle className="ml-1">Para vos</HelpSubtitle>
            </div>

            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="visible"
              className="space-y-3"
            >
              {data.recommendations.map((rec) => (
                <RecommendationCard key={rec.id} rec={rec} />
              ))}
            </motion.div>
          </section>

          <Disclaimer />
        </>
      )}
    </motion.div>
  );
}

// --- Hero del ahorro total -------------------------------------------------

function SavingHero({ count }: { count: number }) {
  return (
    <Card className="overflow-hidden p-5">
      <div className="flex items-center gap-2">
        <Icon name="sparkle" className="h-4 w-4 text-[var(--color-seiji)]" />
        <Label>確認する提案</Label>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-[var(--color-sumi-soft)]">
        実行できる提案が
        <span className="tabular mx-0.5 font-semibold text-[var(--color-sumi)]">
          {count}
        </span>
        件あります。下のカードから手続きに進めます。
      </p>
      <HelpSubtitle className="mt-1.5">
        Las cifras son escenarios independientes y no deben sumarse como ahorro total. Comprueba cada requisito y tus importes reales.
      </HelpSubtitle>
    </Card>
  );
}

// --- Tarjeta de recomendación ----------------------------------------------

function RecommendationCard({ rec }: { rec: Recommendation }) {
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  const priority = PRIORITY_META[rec.priority];
  const status = STATUS_META[rec.status];
  const hasSaving = rec.total_saving > 0;

  return (
    <motion.div variants={recommendationCardVariants}>
      <Card className="p-4 sm:p-5">
        {/* Cabecera: icono + título + badges */}
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-seiji)]">
            <Icon name={CATEGORY_ICON[rec.category]} className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-bold leading-snug text-[var(--color-sumi)]">
                {rec.title_jp}
              </h3>
              <span
                className={`inline-flex shrink-0 items-center rounded-[var(--radius-pill)] border px-2 py-0.5 text-[10px] font-semibold ${priority.className}`}
                title={priority.es}
              >
                {priority.label}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] font-medium text-[var(--color-sumi-soft)]">
              {status.label}
              <HelpSubtitle className="inline">{` · ${status.es}`}</HelpSubtitle>
            </p>
          </div>
        </div>

        {/* Cuerpo: explicación JP + ayuda ES */}
        <p className="mt-3 text-sm leading-relaxed text-[var(--color-sumi)]">
          {rec.body_jp}
        </p>
        <HelpSubtitle className="mt-1.5">{rec.body_es}</HelpSubtitle>

        {/* Ahorro estimado (¥ en mono font) */}
        {hasSaving && (
          <SavingBreakdown
            incomeTax={rec.income_tax_saving}
            residentTax={rec.resident_tax_saving}
            total={rec.total_saving}
          />
        )}

        {/* CTA de acción */}
        {rec.action_route && (
          <button
            type="button"
            onClick={() => setActiveSection(rec.action_route as string)}
            className="mt-4 inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--color-seiji)] bg-[var(--color-seiji-soft)] px-3.5 py-2 text-sm font-medium text-[var(--color-seiji)] transition-colors hover:bg-[var(--color-seiji)] hover:text-white"
          >
            {rec.action_label}
            <Icon name="arrow" className="h-3.5 w-3.5" />
          </button>
        )}
      </Card>
    </motion.div>
  );
}

// --- Desglose del ahorro (所得税 / 住民税 / total) --------------------------

function SavingBreakdown({
  incomeTax,
  residentTax,
  total,
}: {
  incomeTax: number;
  residentTax: number;
  total: number;
}) {
  // Mostramos el desglose solo si ambos componentes aportan (si no, el total
  // ya lo dice todo y evitamos ruido visual).
  const showSplit = incomeTax > 0 && residentTax > 0;

  return (
    <motion.div
      variants={savingAmountVariants}
      initial="hidden"
      animate="visible"
      className="mt-3.5 rounded-[var(--radius-card)] bg-[var(--color-seiji-soft)] px-4 py-3"
    >
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-medium text-[var(--color-seiji)]">
            節税見込み（概算）
            <HelpSubtitle className="inline">{" · Ahorro estimado"}</HelpSubtitle>
          </p>
          {showSplit && (
            <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-[var(--color-sumi-soft)]">
              <span>
                所得税{" "}
                <span className="tabular font-semibold text-[var(--color-sumi)]">
                  {formatYen(incomeTax)}
                </span>
              </span>
              <span>
                住民税{" "}
                <span className="tabular font-semibold text-[var(--color-sumi)]">
                  {formatYen(residentTax)}
                </span>
              </span>
            </p>
          )}
        </div>
        <p className="tabular shrink-0 text-2xl font-bold text-[var(--color-seiji)]">
          {formatYen(total)}
        </p>
      </div>
    </motion.div>
  );
}

// --- Estados auxiliares -----------------------------------------------------

function LoadingSkeletons() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-36 w-full" />
    </div>
  );
}

function EmptyAdvice() {
  return (
    <Card className="px-6 py-12 text-center">
      <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-full bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]">
        <Icon name="check" className="h-6 w-6" />
      </div>
      <p className="text-base font-medium text-[var(--color-sumi)]">
        今のところ追加の提案はありません
      </p>
      <p className="mx-auto mt-1.5 max-w-sm text-sm leading-relaxed text-[var(--color-sumi-soft)]">
        控除や収入を更新すると、新しい節税のヒントがここに表示されます。
      </p>
      <HelpSubtitle className="mt-2">
        No hay recomendaciones nuevas por ahora. Al cargar más 控除 o ingresos,
        aparecerán acá nuevas ideas de ahorro.
      </HelpSubtitle>
    </Card>
  );
}

function Disclaimer() {
  return (
    <p className="mt-8 text-center text-[11px] leading-relaxed text-[var(--color-sumi-soft)]">
      表示される金額はすべて概算です。最終的な判断は申告書・国税庁の案内、必要に応じて税理士にご確認ください。
      <HelpSubtitle className="mt-1">
        Todos los montos son estimaciones (概算). Confirmá con tu declaración, la
        guía del 国税庁 y, si hace falta, un 税理士.
      </HelpSubtitle>
    </p>
  );
}
