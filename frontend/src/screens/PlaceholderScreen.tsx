/**
 * Empty state que GUIA para las secciones aun no implementadas (帳簿/控除/
 * 確定申告/領収書・証明書). En vez de "準備中" pelado: icono + una frase de la VOZ de la
 * interfaz que explica que hara la seccion + un CTA hacia lo que ya esta listo.
 */
import { motion } from "framer-motion";
import type { NavSection } from "../lib/navigation";
import { useUiStore } from "../lib/store";
import { Card } from "../components/ui";
import { Icon, type IconName } from "../components/Icon";
import { screenVariants } from "../variants/layoutVariants";

/** Copy + CTA por seccion dormida (voz clara, japones). */
interface SectionGuide {
  /** Frase que explica que hara la seccion (1-2 lineas). */
  promise: string;
  /** Texto del CTA hacia una seccion ya lista. */
  ctaLabel: string;
  /** Seccion destino del CTA (algo que SI funciona hoy). */
  ctaTarget: string;
}

const SECTION_GUIDES: Record<string, SectionGuide> = {
  books: {
    promise:
      "確認した仕訳から、仕訳帳・総勘定元帳・試算表をここで自動作成します。今は、まず仕訳トレイで取引を承認していきましょう。",
    ctaLabel: "仕訳トレイへ",
    ctaTarget: "journal-tray",
  },
  "deduction-wizard": {
    promise:
      "医療費・社会保険・iDeCo・ふるさと納税など、質問に答えるだけで控除を登録します。控除を入れるほど、納税額は下がります。",
    ctaLabel: "今の見込み額をダッシュボードで見る",
    ctaTarget: "dashboard",
  },
  filing: {
    promise:
      "すべての仕訳と控除がそろうと、申告書（PDF・.xtx・CSV）をここで生成します。まずは領収書の取り込みから始めましょう。",
    ctaLabel: "領収書を撮影",
    ctaTarget: "capture",
  },
  evidence: {
    promise:
      "電子帳簿保存法に対応して、領収書を日付・金額・取引先で検索・保存します。取り込んだ書類がここに集まります。",
    ctaLabel: "領収書を撮影",
    ctaTarget: "capture",
  },
};

export function PlaceholderScreen({ section }: { section: NavSection }) {
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  const guide = SECTION_GUIDES[section.id];

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-2xl px-4 py-6 sm:px-8 sm:py-10"
    >
      <div className="mb-6 flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
          <Icon name={section.icon as IconName} className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-[var(--color-sumi)]">{section.label}</h2>
          <p className="text-sm text-[var(--color-sumi-soft)]">{section.description}</p>
        </div>
      </div>

      <Card className="p-8 sm:p-10">
        <div className="flex flex-col items-center text-center">
          {/* Icono sutil de la seccion (no un vacio mudo). */}
          <div className="relative mb-5 grid h-16 w-16 place-items-center rounded-full bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
            <Icon name={section.icon as IconName} className="h-7 w-7" />
            <span className="absolute -right-1 -top-1 grid h-6 w-6 place-items-center rounded-full border border-[var(--color-hairline)] bg-[var(--color-surface)] text-[var(--color-kohaku)]">
              <Icon name="sparkle" className="h-3.5 w-3.5" />
            </span>
          </div>

          <p className="text-base font-medium text-[var(--color-sumi)]">
            近日公開予定の機能です
          </p>
          <p className="mt-2 max-w-md text-sm leading-relaxed text-[var(--color-sumi-soft)]">
            {guide?.promise ??
              "次のステップで実装されます。今は土台（撮影・仕訳・ダッシュボード・設定）が動いています。"}
          </p>

          {guide && (
            <button
              type="button"
              onClick={() => setActiveSection(guide.ctaTarget)}
              className="mt-6 flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
            >
              {guide.ctaLabel}
              <Icon name="arrow" className="h-4 w-4" />
            </button>
          )}
        </div>
      </Card>
    </motion.div>
  );
}
