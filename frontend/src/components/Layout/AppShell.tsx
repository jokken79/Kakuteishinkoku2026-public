/**
 * App shell: header (年度 + impuesto estimado en vivo) + sidebar serena en
 * desktop / bottom-nav en movil. Layout con whitespace generoso (間).
 *
 * Nav móvil: 5 ítems core en la barra + botón "もっと" que abre MobileMoreSheet
 * con todas las secciones restantes.
 */
import { useState } from "react";
import { motion } from "framer-motion";
import { MOBILE_PRIMARY_IDS, NAV_GROUPS, NAV_SECTIONS } from "../../lib/navigation";
import { useFiscalYears } from "../../lib/hooks";
import { preloadScreen } from "../../lib/screenRegistry";
import { useUiStore } from "../../lib/store";
import { Icon, type IconName } from "../Icon";
import { ConnectionBadge } from "../ConnectionBadge";
import { HelpSubtitle, HelpToggle } from "../HelpTerm";
import { LiveTaxChip } from "./LiveTaxChip";
import { YearSelector } from "./YearSelector";
import { ToastViewport } from "./ToastViewport";
import { MobileMoreSheet } from "./MobileMoreSheet";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const activeSection = useUiStore((s) => s.activeSection);
  const activeYear = useUiStore((s) => s.activeYear);
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  const { data: fiscalYears } = useFiscalYears();
  const [moreOpen, setMoreOpen] = useState(false);

  const currentFiscalYear = fiscalYears?.years.find((fy) => fy.year === activeYear);
  const isReadOnly =
    currentFiscalYear?.status === "closed" || currentFiscalYear?.status === "filed";

  const mobilePrimarySections = NAV_SECTIONS.filter((s) =>
    (MOBILE_PRIMARY_IDS as readonly string[]).includes(s.id),
  );

  return (
    <div className="flex h-full flex-col bg-[var(--color-paper)]">
      {import.meta.env.VITE_DEMO_MODE === "true" && (
        <div className="bg-amber-100 px-3 py-2 text-center text-sm font-semibold text-amber-950" role="status">
          デモモード・架空データ / DEMOSTRACIÓN: datos ficticios; no son tu declaración real.
        </div>
      )}
      {/* Header */}
      <header className="z-20 flex items-center justify-between gap-2 border-b border-[var(--color-hairline)] bg-[var(--color-paper)]/90 px-3 py-3 backdrop-blur sm:gap-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          {/* Marca: sello en tinta sumi (sin relleno rojo — el 朱色 se reserva
              para confirmar). Contorno de sello con el 申 en tinta. */}
          <div
            className="grid h-8 w-8 place-items-center rounded-md border-[1.5px] border-[var(--color-sumi)] text-[13px] font-bold text-[var(--color-sumi)]"
            aria-hidden
          >
            申
          </div>
          <div className="leading-tight">
            <h1 className="text-[15px] font-bold tracking-tight text-[var(--color-sumi)]">
              確定申告
            </h1>
            <HelpSubtitle className="hidden text-[11px] sm:block">
              Declaración de la renta
            </HelpSubtitle>
          </div>
          {/* Selector de 年度: cambia el año fiscal activo de toda la app. */}
          <YearSelector />
        </div>
        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          <LiveTaxChip />
          <HelpToggle variant="compact" />
          <div className="hidden sm:block">
            <ConnectionBadge />
          </div>
        </div>
      </header>

      {/* Body: sidebar (desktop) + content */}
      <div className="flex min-h-0 flex-1">
        {/* Sidebar desktop */}
        <nav className="hidden w-56 shrink-0 flex-col overflow-y-auto border-r border-[var(--color-hairline)] bg-[var(--color-paper)] px-3 pb-3 lg:flex">
          {NAV_GROUPS.map((group, index) => (
            <div key={group.id} className={index === 0 ? "pt-2" : "pt-3"}>
              <p className="flex items-baseline gap-1.5 px-3 pb-1 text-[9px] font-semibold text-[var(--color-sumi-soft)]">
                <span>{group.label}</span>
                <span className="font-normal">{group.es}</span>
              </p>
              <div className="space-y-0.5">
                {NAV_SECTIONS.filter((section) => section.group === group.id).map((section) => (
                  <NavButton
                    key={section.id}
                    icon={section.icon as IconName}
                    label={section.label}
                    es={section.es}
                    ready={section.ready}
                    selected={section.id === activeSection}
                    onClick={() => setActiveSection(section.id)}
                    onPreload={() => preloadScreen(section.id)}
                  />
                ))}
              </div>
            </div>
          ))}
          <p className="mt-auto px-3 pt-4 text-[10px] leading-relaxed text-[var(--color-sumi-soft)]">
            本アプリは申告の補助ツールです。最終的な内容はご自身でご確認ください。
          </p>
        </nav>

        {/* Content */}
        <main className="min-w-0 flex-1 overflow-auto pb-24 lg:pb-0">
          {isReadOnly && (
            <div
              className="flex items-start gap-2 border-b border-[var(--color-hairline)] bg-[var(--color-kohaku-soft)] px-4 py-2.5 text-[var(--color-sumi)] sm:px-6"
              role="status"
            >
              <Icon
                name="shield"
                className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-kohaku)]"
              />
              <div className="min-w-0 text-xs leading-relaxed">
                <span className="font-semibold">この年度は閲覧のみです。</span>
                <HelpSubtitle className="text-[var(--color-sumi)]">
                  El año está cerrado o presentado; los datos fiscales no se pueden modificar.
                </HelpSubtitle>
              </div>
            </div>
          )}
          {children}
        </main>
      </div>

      {/* Bottom-nav móvil: 5 ítems core + botón もっと */}
      <nav
        aria-label="メインナビゲーション"
        className="fixed inset-x-0 bottom-0 z-20 flex items-stretch justify-around border-t border-[var(--color-hairline)] bg-[var(--color-surface)]/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
      >
        {mobilePrimarySections.map((section) => {
          const selected = section.id === activeSection;
          return (
            <button
              key={section.id}
              type="button"
              onPointerEnter={() => preloadScreen(section.id)}
              onFocus={() => preloadScreen(section.id)}
              onClick={() => setActiveSection(section.id)}
              aria-current={selected ? "page" : undefined}
              className="relative flex min-h-[58px] flex-1 flex-col items-center justify-center gap-1 px-1 py-2"
            >
              <Icon
                name={section.icon as IconName}
                className={`h-[22px] w-[22px] transition-colors ${selected ? "text-[var(--color-sumi)]" : "text-[var(--color-sumi-soft)]"}`}
              />
              <span
                className={`text-[10px] transition-colors ${selected ? "font-semibold text-[var(--color-sumi)]" : "text-[var(--color-sumi-soft)]"}`}
              >
                {section.short}
              </span>
              <HelpSubtitle className="text-center text-[8px] leading-none">
                {section.es}
              </HelpSubtitle>
              {selected && (
                <motion.span
                  layoutId="mobile-nav-indicator"
                  className="absolute top-0 h-0.5 w-8 rounded-full bg-[var(--color-seiji)]"
                />
              )}
            </button>
          );
        })}

        {/* Botón もっと (Más) — abre el sheet con el resto de secciones */}
        <button
          type="button"
          onClick={() => setMoreOpen(true)}
          aria-label="その他のメニューを開く"
          aria-expanded={moreOpen}
          aria-haspopup="dialog"
          className="relative flex min-h-[58px] flex-1 flex-col items-center justify-center gap-1 px-1 py-2"
        >
          <Icon
            name="menu"
            className="h-[22px] w-[22px] text-[var(--color-sumi-soft)] transition-colors"
          />
          <span className="text-[10px] text-[var(--color-sumi-soft)]">
            もっと
          </span>
          <HelpSubtitle className="text-center text-[8px] leading-none">
            Más
          </HelpSubtitle>
        </button>
      </nav>

      {/* Sheet "もっと": el resto de secciones en móvil */}
      <MobileMoreSheet open={moreOpen} onClose={() => setMoreOpen(false)} />

      {/* Toasts (micro-feedback de guardado, sereno) */}
      <ToastViewport />
    </div>
  );
}

function NavButton({
  icon,
  label,
  es,
  selected,
  ready,
  onClick,
  onPreload,
}: {
  icon: IconName;
  label: string;
  es: string;
  selected: boolean;
  ready: boolean;
  onClick: () => void;
  onPreload: () => void;
}) {
  return (
    <button
      type="button"
      onPointerEnter={onPreload}
      onFocus={onPreload}
      onClick={onClick}
      aria-current={selected ? "page" : undefined}
      className={[
        "group relative flex items-center gap-3 rounded-[10px] px-3 py-2 text-left text-sm transition-colors",
        selected
          ? "bg-[var(--color-surface)] font-semibold text-[var(--color-sumi)] shadow-[var(--shadow-paper)]"
          : "text-[var(--color-sumi-soft)] hover:bg-[var(--color-paper-sink)]",
      ].join(" ")}
    >
      {selected && (
        <motion.span
          layoutId="sidebar-indicator"
          className="absolute left-0 h-5 w-[3px] rounded-full bg-[var(--color-seiji)]"
        />
      )}
      <Icon
        name={icon}
        className={`h-[18px] w-[18px] ${selected ? "text-[var(--color-sumi)]" : ""}`}
      />
      <span className="min-w-0 flex-1">
        <span className="block truncate">{label}</span>
        <HelpSubtitle>{es}</HelpSubtitle>
      </span>
      {!ready && (
        <span className="rounded-full bg-[var(--color-paper-sink)] px-1.5 py-0.5 text-[9px] text-[var(--color-sumi-soft)]">
          準備中
        </span>
      )}
    </button>
  );
}
