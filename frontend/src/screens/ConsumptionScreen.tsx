/**
 * 消費税 (impuesto al consumo / インボイス).
 *
 * Solo es relevante para 課税事業者 (negocios obligados, p.ej. ventas base
 * > ¥10M o inscritos como インボイス). El owner es 免税事業者 por defecto: en ese
 * caso la pantalla muestra un estado informativo claro ("申告不要") con la
 * explicacion ES de cuando corresponde registrarse.
 *
 * Para 課税事業者 muestra escenarios sin verificar elegibilidad y un informe
 * orientativo, que no es un formulario de declaración.
 */
import { motion } from "framer-motion";
import {
  consumptionPdfUrl,
  type ConsumptionMethodKey,
  type ConsumptionOption,
  type ConsumptionResult,
} from "../lib/api";
import { useConsumption, useTaxpayer } from "../lib/hooks";
import { useUiStore } from "../lib/store";
import { formatYen } from "../lib/format";
import { Card, ErrorState, Label, Skeleton } from "../components/ui";
import { Icon } from "../components/Icon";
import { HelpSubtitle, HelpTerm } from "../components/HelpTerm";
import {
  screenVariants,
  staggerContainer,
  staggerItem,
} from "../variants/layoutVariants";

export function ConsumptionScreen() {
  const { data: taxpayer } = useTaxpayer();
  const { data, isLoading, isError, refetch } = useConsumption();

  const isTaxable = data?.is_taxable ?? taxpayer?.is_taxable_consumption ?? false;

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-3xl px-4 py-6 pb-24 sm:px-8 sm:py-10"
    >
      <header className="mb-6 flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
          <Icon name="box" className="h-5 w-5" />
        </div>
        <div>
          <h2 className="flex items-center text-xl font-bold text-[var(--color-sumi)]">
            消費税
            <HelpTerm term="消費税" size="md" />
          </h2>
          <HelpSubtitle term="消費税" />
          <p className="text-sm text-[var(--color-sumi-soft)]">
            課税事業者の消費税（インボイス制度）
          </p>
        </div>
      </header>

      {isLoading && <ConsumptionSkeleton />}

      {isError && (
        <Card className="p-2">
          <ErrorState
            message="消費税の計算に失敗しました。バックエンドの接続をご確認ください。"
            onRetry={() => void refetch()}
          />
        </Card>
      )}

      {data && !isLoading && (
        isTaxable ? (
          <TaxableView result={data} />
        ) : (
          <MenzeiView />
        )
      )}
    </motion.div>
  );
}

// --- Estado 免税事業者 (informativo) ----------------------------------------

function MenzeiView() {
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  return (
    <motion.div variants={staggerContainer} initial="hidden" animate="visible">
      <motion.div variants={staggerItem}>
        <Card className="overflow-hidden">
          <div className="flex items-center gap-3 border-b border-[var(--color-hairline)] bg-[var(--color-seiji-soft)] px-5 py-4">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[var(--color-seiji)] text-white">
              <Icon name="check" className="h-4 w-4" />
            </span>
            <div>
              <p className="flex items-center text-sm font-semibold text-[var(--color-seiji)]">
                免税事業者として設定されています
                <HelpTerm term="免税事業者" />
              </p>
              <HelpSubtitle term="免税事業者" />
            </div>
          </div>
          <div className="px-5 py-5">
            <p className="text-sm leading-relaxed text-[var(--color-sumi)]">
              現在の設定は<strong>免税事業者</strong>です。実際の申告義務は自動確認されていません。
            </p>
            <HelpSubtitle className="mt-2">
              La app está configurada como exenta, pero no ha comprobado si
              realmente tienes obligación de declarar 消費税. Revisa tus ventas,
              registro インボイス y demás circunstancias antes de decidir.
            </HelpSubtitle>

            <div className="mt-5 rounded-[var(--radius-card)] bg-[var(--color-paper-sink)] p-4">
              <p className="text-xs font-semibold text-[var(--color-sumi)]">
                課税事業者になるのはどんなとき？
              </p>
              <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-[var(--color-sumi-soft)]">
                <li>
                  ・基準期間（前々年）の課税売上高が <strong>1,000万円</strong> を超えたとき
                </li>
                <li>
                  ・<HelpTerm term="インボイス" />
                  （適格請求書）発行事業者として登録したとき（取引先が控除に必要）
                </li>
              </ul>
              <HelpSubtitle className="mt-3">
                Te conviertes en 課税事業者 si tus ventas gravadas del periodo base
                superan 10 millones de yenes, o si te registras como emisor de
                facturas インボイス (porque tus clientes lo necesitan para deducir
                su IVA).
              </HelpSubtitle>
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-2 text-xs text-[var(--color-sumi-soft)]">
              <span>課税事業者として申告する場合：</span>
              <button
                type="button"
                onClick={() => setActiveSection("settings")}
                className="inline-flex items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-3 py-1.5 font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
              >
                <Icon name="gear" className="h-3.5 w-3.5" />
                設定で切り替え
              </button>
            </div>
          </div>
        </Card>
      </motion.div>
    </motion.div>
  );
}

// --- Estado 課税事業者 (comparacion completa) -------------------------------

const METHOD_LABEL_ES: Record<ConsumptionMethodKey, string> = {
  honsoku: "Régimen general",
  kani: "Régimen simplificado",
  tokurei: "Especial 20% / 30%",
};

const METHOD_TERM: Record<ConsumptionMethodKey, string> = {
  honsoku: "本則課税",
  kani: "簡易課税",
  tokurei: "2割特例",
};

function TaxableView({ result }: { result: ConsumptionResult }) {
  const options: ConsumptionOption[] = [
    result.honsoku,
    result.kani,
    result.tokurei,
  ];
  const recommended = options.find(
    (o) => o.method === result.recommended,
  );

  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      animate="visible"
      className="space-y-5"
    >
      <Card className="p-5">
        <p className="font-semibold">Simulación: requisitos pendientes de comprobar</p>
        <p className="mt-2 text-sm">La app no puede recomendar un método hasta verificar, entre otros datos, las ventas del período base, los avisos presentados y tu registro インボイス. Los importes son aproximados y no confirman el derecho a aplicar ningún régimen.</p>
        <a className="mt-2 inline-block underline" href="https://www.nta.go.jp/publication/pamph/shohi/kaisei/202304/01.htm" target="_blank" rel="noopener noreferrer">Requisitos de 2割特例 — 国税庁</a>
      </Card>
      {/* Recomendacion destacada */}
      {recommended && (
        <motion.div variants={staggerItem}>
          <RecommendedBanner
            option={recommended}
            saving={result.recommended_saving}
          />
        </motion.div>
      )}

      {/* Comparacion de las 3 opciones */}
      <motion.div variants={staggerItem}>
        <div className="mb-3 flex items-center gap-2">
          <Icon name="compass" className="h-4 w-4 text-[var(--color-sumi-soft)]" />
          <Label>計算方法の比較</Label>
          <HelpSubtitle className="ml-1">Comparación de los 3 métodos</HelpSubtitle>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {options.map((opt) => (
            <MethodCard
              key={opt.method}
              option={opt}
              isRecommended={opt.method === result.recommended}
              showEstimate={opt.method !== "kani" || result.business_category != null}
            />
          ))}
        </div>
      </motion.div>

      {/* Desglose 売上税額 / 仕入税額控除 (8% / 10%) */}
      <motion.div variants={staggerItem}>
        <BreakdownCard result={result} />
      </motion.div>

      {/* Descargar el 消費税申告書 (PDF) */}
      <motion.div variants={staggerItem}>
        <DownloadCard year={result.year} />
      </motion.div>
    </motion.div>
  );
}

function RecommendedBanner({
  option,
  saving,
}: {
  option: ConsumptionOption;
  saving: number;
}) {
  return (
    <Card className="overflow-hidden border-[var(--color-seiji)]">
      <div className="bg-[var(--color-seiji-soft)] px-5 py-3">
        <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--color-seiji)]">
          <Icon name="sparkle" className="h-3.5 w-3.5" />
          おすすめの計算方法
        </p>
        <HelpSubtitle>Método recomendado (el de menor pago)</HelpSubtitle>
      </div>
      <div className="flex flex-wrap items-end justify-between gap-4 px-5 py-4">
        <div>
          <p className="flex items-center text-base font-bold text-[var(--color-sumi)]">
            {option.label}
            <HelpTerm term={METHOD_TERM[option.method]} />
          </p>
          {option.note && (
            <p className="mt-0.5 text-xs text-[var(--color-sumi-soft)]">
              {option.note}
            </p>
          )}
        </div>
        <div className="text-right">
          <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--color-seiji)]">
            納付税額
          </p>
          <p className="tabular text-3xl font-bold text-[var(--color-seiji)]">
            {formatYen(option.total_tax)}
          </p>
        </div>
      </div>
      {saving > 0 && (
        <div className="border-t border-[var(--color-hairline)] bg-[var(--color-surface)] px-5 py-2.5">
          <p className="text-xs text-[var(--color-sumi-soft)]">
            最も高い方法より
            <span className="tabular mx-1 font-semibold text-[var(--color-seiji)]">
              {formatYen(saving)}
            </span>
            少なくなります。
          </p>
        </div>
      )}
    </Card>
  );
}

function MethodCard({
  option,
  isRecommended,
  showEstimate,
}: {
  option: ConsumptionOption;
  isRecommended: boolean;
  showEstimate: boolean;
}) {
  const muted = option.eligibility_status === "unavailable";
  return (
    <div
      className={`relative rounded-[var(--radius-card)] border p-4 shadow-[var(--shadow-paper)] ${
        isRecommended
          ? "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)]"
          : "border-[var(--color-hairline)] bg-[var(--color-surface)]"
      } ${muted ? "opacity-55" : ""}`}
    >
      {isRecommended && (
        <span className="absolute -top-2 right-3 rounded-[var(--radius-pill)] bg-[var(--color-seiji)] px-2 py-0.5 text-[10px] font-semibold text-white">
          推奨
        </span>
      )}
      <p className="flex items-center text-sm font-semibold text-[var(--color-sumi)]">
        {option.label}
        <HelpTerm term={METHOD_TERM[option.method]} />
      </p>
      <HelpSubtitle className="mt-0.5">
        {METHOD_LABEL_ES[option.method]}
      </HelpSubtitle>

      {option.eligibility_status !== "unavailable" && showEstimate ? (
        <>
          <p
            className={`tabular mt-3 text-2xl font-bold ${
              isRecommended
                ? "text-[var(--color-seiji)]"
                : "text-[var(--color-sumi)]"
            }`}
          >
            {formatYen(option.total_tax)}
          </p>
          <p className="text-[11px] text-[var(--color-sumi-soft)]">Estimación · elegibilidad sin verificar</p>
          <dl className="mt-3 space-y-1 border-t border-[var(--color-hairline)] pt-2 text-[11px] text-[var(--color-sumi-soft)]">
            <Row label="仕入税額控除" value={option.purchase_tax_credit} />
            <Row label="国税分" value={option.national_tax} />
            <Row label="地方消費税" value={option.local_tax} />
          </dl>
        </>
      ) : (
        <div className="mt-3 rounded-lg bg-[var(--color-paper-sink)] px-3 py-3">
          <p className="text-xs font-medium text-[var(--color-sumi-soft)]">
            {showEstimate ? "対象外" : "Falta seleccionar 事業区分"}
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--color-sumi-soft)]">
            {option.note ?? "この事業者には適用できません。"}
          </p>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between">
      <dt>{label}</dt>
      <dd className="tabular font-medium text-[var(--color-sumi)]">
        {formatYen(value)}
      </dd>
    </div>
  );
}

function BreakdownCard({ result }: { result: ConsumptionResult }) {
  const sb = result.sales_breakdown;
  const pb = result.purchase_breakdown;
  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center gap-2">
        <Icon name="tray" className="h-4 w-4 text-[var(--color-sumi-soft)]" />
        <Label>内訳（区分経理 8% / 10%）</Label>
      </div>

      {/* 売上税額 */}
      <div className="rounded-[var(--radius-card)] bg-[var(--color-paper-sink)] p-4">
        <p className="flex items-center text-sm font-semibold text-[var(--color-sumi)]">
          売上税額
          <HelpTerm term="売上税額" />
        </p>
        <dl className="mt-2 space-y-1.5 text-xs text-[var(--color-sumi-soft)]">
          <BreakdownRow
            label="課税売上 10%（税込）"
            value={sb.taxable_sales_10}
            tax={sb.national_tax_10}
          />
          <BreakdownRow
            label="課税売上 8%（軽減・税込）"
            value={sb.taxable_sales_8}
            tax={sb.national_tax_8}
          />
          <div className="flex items-center justify-between border-t border-[var(--color-hairline)] pt-1.5">
            <dt className="font-semibold text-[var(--color-sumi)]">
              売上に係る消費税額（国税分）
            </dt>
            <dd className="tabular font-bold text-[var(--color-sumi)]">
              {formatYen(sb.national_tax_total)}
            </dd>
          </div>
        </dl>
      </div>

      {/* 仕入税額控除 (本則) */}
      <div className="mt-3 rounded-[var(--radius-card)] bg-[var(--color-paper-sink)] p-4">
        <p className="flex items-center text-sm font-semibold text-[var(--color-sumi)]">
          仕入税額控除（本則）
          <HelpTerm term="仕入税額控除" />
        </p>
        <p className="mt-2 text-sm">Simulación basada en indicadores automáticos de recibos, no en facturas verificadas. El OCR solo comprueba el formato del número; consulta la inscripción y vigencia en la fecha de la operación en el <a className="underline" href="https://www.invoice-kohyo.nta.go.jp/" target="_blank" rel="noopener noreferrer">sitio de 国税庁</a>. Si faltan tasas, el cálculo puede asumir el 10 %. Revisa documentos y excepciones antes de declarar.</p>
        <dl className="mt-2 space-y-1.5 text-xs text-[var(--color-sumi-soft)]">
          <BreakdownRow
            label="候補（未検証）10%（税込）"
            value={pb.qualified_purchases_10}
            tax={pb.national_tax_10}
          />
          <BreakdownRow
            label="候補（未検証）8%（税込）"
            value={pb.qualified_purchases_8}
            tax={pb.national_tax_8}
          />
          <div className="flex items-center justify-between border-t border-[var(--color-hairline)] pt-1.5">
            <dt className="font-semibold text-[var(--color-sumi)]">
              控除候補の試算（国税分・未検証）
            </dt>
            <dd className="tabular font-bold text-[var(--color-sumi)]">
              {formatYen(pb.national_tax_total)}
            </dd>
          </div>
        </dl>
        {pb.excluded_non_qualified > 0 && (
          <p className="mt-2 flex items-center text-[11px] leading-relaxed text-[var(--color-kohaku)]">
            <Icon name="shield" className="mr-1 h-3 w-3 shrink-0" />
            La simulación excluye {formatYen(pb.excluded_non_qualified)} en gastos sin indicador de número válido. Eso no determina si una compra cumple los requisitos; algunas pueden tener un crédito transitorio no calculado aquí.
          </p>
        )}
      </div>
    </Card>
  );
}

function BreakdownRow({
  label,
  value,
  tax,
}: {
  label: string;
  value: number;
  tax: number;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="min-w-0 truncate">{label}</dt>
      <dd className="tabular shrink-0 text-[var(--color-sumi)]">
        {formatYen(value)}
        <span className="ml-2 text-[var(--color-sumi-soft)]">
          税 {formatYen(tax)}
        </span>
      </dd>
    </div>
  );
}

function DownloadCard({ year }: { year: number }) {
  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center gap-2">
        <Icon name="file" className="h-4 w-4 text-[var(--color-sumi-soft)]" />
        <Label>消費税の参考計算</Label>
        <HelpSubtitle className="ml-1">Informe de simulación (PDF)</HelpSubtitle>
      </div>
      <p className="text-sm leading-relaxed text-[var(--color-sumi-soft)]">
        Informe orientativo de {year}. No es un formulario oficial ni sirve para presentar la declaración.
      </p>
      <a
        href={consumptionPdfUrl(year)}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-4 inline-flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
      >
        <Icon name="file" className="h-4 w-4" />
        Descargar informe de simulación (PDF)
      </a>
    </Card>
  );
}

// --- Skeleton --------------------------------------------------------------

function ConsumptionSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-28 w-full" />
      <div className="grid gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-44 w-full" />
        ))}
      </div>
      <Skeleton className="h-48 w-full" />
    </div>
  );
}
