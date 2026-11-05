/**
 * Dashboard (ダッシュボード). Heroe = 還付金/納付額 grande en mono tabular con
 * sub-label calmo. Debajo: tarjetas serenas (recibos por revisar, deducciones,
 * dias hasta el plazo, progreso). Datos reales del backend.
 */
import { motion } from "framer-motion";
import {
  useFilingDraft,
  usePendingReceipts,
  useRecommendations,
} from "../lib/hooks";
import { useUiStore } from "../lib/store";
import { useActiveYear } from "../lib/hooks";
import {
  filingDeadlineForYear,
  daysUntil,
  formatAmount,
  formatYen,
} from "../lib/format";
import { Card, Label } from "../components/ui";
import { Icon, type IconName } from "../components/Icon";
import { HelpSubtitle } from "../components/HelpTerm";
import {
  heroAmountVariants,
  screenVariants,
  staggerContainer,
  staggerItem,
} from "../variants/layoutVariants";

export function DashboardScreen() {
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  const { data: receipts, isLoading: loadingReceipts, isError: receiptsError } = usePendingReceipts();
  const pendingCount = receipts?.length ?? 0;
  const pendingExpenses = (receipts ?? []).reduce(
    (sum, t) => sum + (t.total_amount ?? 0),
    0,
  );
  // Fuente unica de verdad del 予想納税額: el MISMO motor que la pantalla
  // 確定申告 (`/filing/draft`). Asi el numero del hero coincide exactamente con
  // el 納付額 del filing y con el chip del header (no se recalcula en cliente).
  const { data: tax, isLoading: loadingTax, isError: taxError } = useFilingDraft();
  // Recomendaciones de 節税 (motor plan 08): se destacan en el dashboard para que
  // el owner VEA las ideas de ahorro de un vistazo y entre al panel completo.
  const { data: recommendations } = useRecommendations();

  const activeYear = useActiveYear();
  const isRefund = tax?.is_refund ?? false;
  const deadline = filingDeadlineForYear(activeYear);
  const days = daysUntil(deadline);
  const deadlineLabel = `${deadline.getFullYear()}年${deadline.getMonth() + 1}月${deadline.getDate()}日締切（通常）`;

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-4xl px-4 py-6 sm:px-8 sm:py-10"
    >
      {/* Heroe: 還付見込み (celadon = buena noticia) / 予想納税額 (sumi).
          El color comunica de un vistazo si es a favor o a pagar. */}
      <section className="mb-8">
        <Label>{isRefund ? "還付見込み" : "予想納税額"}</Label>
        <HelpSubtitle className="mt-0.5">
          {isRefund
            ? "Devolución estimada (dinero a tu favor)"
            : "Impuesto estimado a pagar"}
        </HelpSubtitle>
        {taxError ? (
          <p role="alert" className="mt-3 text-sm text-[var(--color-shuiro)]">No se pudo cargar la estimación. Revisa la conexión y vuelve a intentarlo.</p>
        ) : loadingTax || !tax ? (
          <div className="mt-3 h-16 w-64 animate-pulse rounded-lg bg-[var(--color-paper-sink)]" />
        ) : (
          <motion.div
            variants={heroAmountVariants}
            initial="hidden"
            animate="visible"
            className="mt-2 flex items-end gap-2"
          >
            <span
              className={`tabular text-3xl font-medium leading-none ${isRefund ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]"}`}
            >
              ¥
            </span>
            <span
              className={`tabular text-6xl font-bold leading-none tracking-tight sm:text-7xl ${isRefund ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi)]"}`}
            >
              {/* Siempre el valor absoluto: el signo lo dice el color + label. */}
              {formatAmount(tax.final_amount)}
            </span>
            {isRefund && (
              <span className="mb-1.5 ml-1 rounded-[var(--radius-pill)] bg-[var(--color-seiji-soft)] px-2.5 py-1 text-xs font-medium text-[var(--color-seiji)]">
                戻ってくる見込み
              </span>
            )}
          </motion.div>
        )}
        <p className="mt-3 max-w-md text-sm leading-relaxed text-[var(--color-sumi-soft)]">
          {isRefund
            ? "現在の入力では、払いすぎた税金が還付される見込みです。未確認の仕訳を承認すると、金額はさらに更新されます。"
            : "現在の入力に基づく納税見込みです。控除を追加すると金額は下がります。"}
        </p>
        {tax && <p className="mt-2 max-w-lg text-sm text-[var(--color-sumi)]">
          所得税 y 復興特別所得税 estimados: {formatYen(tax.total_tax)}. Retenciones y 予定納税 registrados: {formatYen(tax.withholding_total)}. Si faltan tu 源泉徴収票 o el importe de 予定納税, el saldo podría ser demasiado alto. El 住民税 se calcula aparte.
        </p>}
        {activeYear === 2026 && (
          <p className="mt-2 max-w-lg text-sm text-[var(--color-sumi)]">
            2026年分は暫定計算です。一部の控除と住民税は要確認です。
            Estimación provisional: revisa las deducciones y el 住民税.
          </p>
        )}
      </section>

      {/* Recomendaciones de 節税 destacadas (motor plan 08). Solo si hay algo
          accionable: nunca un banner vacío. */}
      {recommendations && recommendations.actionable_count > 0 && (
        <motion.button
          type="button"
          variants={staggerItem}
          initial="hidden"
          animate="visible"
          onClick={() => setActiveSection("recommendations")}
          className="group mb-4 flex w-full items-center gap-4 rounded-[var(--radius-card)] border border-[var(--color-seiji)] bg-[var(--color-seiji-soft)] px-5 py-4 text-left transition-shadow hover:shadow-[var(--shadow-lift)]"
        >
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-[var(--color-surface)] text-[var(--color-seiji)]">
            <Icon name="sparkle" className="h-5 w-5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-[var(--color-sumi)]">
              節税のヒントが{recommendations.actionable_count}件あります
            </span>
            <span className="mt-0.5 block text-xs leading-relaxed text-[var(--color-sumi-soft)]">適用条件と金額を確認してください。</span>
            <HelpSubtitle className="mt-0.5">
              {`Hay ${recommendations.actionable_count} ideas para revisar. La elegibilidad y el ahorro dependen de tus datos.`}
            </HelpSubtitle>
          </span>
          <Icon
            name="arrow"
            className="h-4 w-4 shrink-0 text-[var(--color-seiji)] transition-transform group-hover:translate-x-0.5"
          />
        </motion.button>
      )}

      {/* Tarjetas serenas */}
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2"
      >
        <motion.div variants={staggerItem}>
          <ActionCard
            icon="tray"
            tone={pendingCount > 0 ? "amber" : "calm"}
            title="要確認の仕訳"
            es="Asientos por revisar"
            onClick={() => setActiveSection("journal-tray")}
            cta="トレイを開く"
          >
            {loadingReceipts ? (
              <div className="h-9 w-16 animate-pulse rounded bg-[var(--color-paper-sink)]" />
            ) : receiptsError ? (
              <p role="alert" className="text-sm">No se pudo cargar</p>
            ) : (
              <p className="flex items-baseline gap-1.5">
                <span className="tabular text-4xl font-bold text-[var(--color-sumi)]">
                  {pendingCount}
                </span>
                <span className="text-sm text-[var(--color-sumi-soft)]">件</span>
              </p>
            )}
          </ActionCard>
        </motion.div>

        <motion.div variants={staggerItem}>
          <ActionCard
            icon="calendar"
            tone={days <= 30 ? "amber" : "calm"}
            title={days < 0 ? "通常の提出期限から" : "提出期限まで"}
            es={days < 0 ? "Días desde el plazo habitual" : "Días hasta el plazo habitual"}
            cta={deadlineLabel}
          >
            <p className="flex items-baseline gap-1.5">
              <span className="tabular text-4xl font-bold text-[var(--color-sumi)]">
                {Math.abs(days)}
              </span>
              <span className="text-sm text-[var(--color-sumi-soft)]">日</span>
            </p>
          </ActionCard>
        </motion.div>

        <motion.div variants={staggerItem}>
          <ActionCard
            icon="receipt"
            tone="calm"
            title="経費（未確認分）"
            es="Gastos (sin confirmar)"
            cta="OCRで読み取り済み"
          >
            <p className="tabular text-3xl font-bold text-[var(--color-sumi)]">
              {receiptsError ? "—" : loadingReceipts ? "…" : formatYen(pendingExpenses)}
            </p>
          </ActionCard>
        </motion.div>

        <motion.div variants={staggerItem}>
          <ActionCard
            icon="check"
            tone="calm"
            title="控除（適用済み）"
            es="Deducciones aplicadas"
            onClick={() => setActiveSection("deduction-wizard")}
            cta="控除ウィザードで追加"
          >
            {tax ? (
              <p className="tabular text-3xl font-bold text-[var(--color-sumi)]">
                {formatYen(tax.total_income_deductions)}
              </p>
            ) : (
              <div className="h-8 w-24 animate-pulse rounded bg-[var(--color-paper-sink)]" />
            )}
          </ActionCard>
        </motion.div>
      </motion.div>

      {/* Estado de los datos: no implica declaración completa ni presentada. */}
      <motion.div variants={staggerItem} initial="hidden" animate="visible">
        <Card className="mt-4 p-5">
          <Label>申告の確認事項 · Datos por revisar</Label>
          {tax && tax.checklist.some((item) => !item.done) ? (
            <ul className="mt-3 space-y-2">
              {tax.checklist.filter((item) => !item.done).map((item) => (
                <li key={item.key} className="text-sm text-[var(--color-sumi)]">
                  • {item.label}{item.detail ? ` — ${item.detail}` : ""}
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-sm">{tax ? "No hay avisos pendientes en esta lista. Revisa igualmente todos los datos y formularios." : taxError ? "No se pudo cargar la lista de revisión." : "Cargando la lista de revisión…"}</p>}
          <p className="mt-3 text-xs leading-relaxed text-[var(--color-sumi-soft)]">Esta lista es orientativa: no confirma que la declaración esté completa ni presentada.</p>
          <button type="button" onClick={() => setActiveSection("filing")}
            className="mt-3 text-sm font-medium text-[var(--color-seiji)]">Ver declaración y lista completa →</button>
        </Card>
      </motion.div>
    </motion.div>
  );
}

function ActionCard({
  icon,
  title,
  es,
  tone,
  cta,
  onClick,
  children,
}: {
  icon: IconName;
  title: string;
  /** Subtitulo ES opcional (capa de ayuda; UI sigue en japones). */
  es?: string;
  tone: "calm" | "amber";
  cta: string;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  const interactive = Boolean(onClick);
  const accent =
    tone === "amber"
      ? "text-[var(--color-kohaku)]"
      : "text-[var(--color-sumi-soft)]";

  return (
    <Card
      className={`flex h-full flex-col p-5 transition-shadow ${interactive ? "cursor-pointer hover:shadow-[var(--shadow-lift)]" : ""}`}
    >
      <div className="mb-3 flex items-start justify-between">
        <span>
          <span className="block text-sm font-medium text-[var(--color-sumi)]">
            {title}
          </span>
          {es && <HelpSubtitle>{es}</HelpSubtitle>}
        </span>
        <Icon name={icon} className={`h-5 w-5 shrink-0 ${accent}`} />
      </div>
      <div className="mb-3">{children}</div>
      <button
        type="button"
        onClick={onClick}
        disabled={!interactive}
        aria-label={interactive ? `${title} — ${cta}` : undefined}
        className={`mt-auto flex items-center gap-1 rounded text-left text-xs font-medium ${interactive ? "text-[var(--color-seiji)]" : "text-[var(--color-sumi-soft)]"}`}
      >
        {cta}
        {interactive && <Icon name="arrow" className="h-3.5 w-3.5" />}
      </button>
    </Card>
  );
}
