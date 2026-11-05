import { lazy, type ComponentType } from "react";

type ScreenComponent = ComponentType<Record<string, never>>;
type ScreenLoader = () => Promise<{ default: ScreenComponent }>;

function lazyScreen(loader: ScreenLoader) {
  return lazy(loader);
}

const SCREEN_LOADERS: Record<string, ScreenLoader> = {
  dashboard: () =>
    import("../screens/DashboardScreen").then((module) => ({
      default: module.DashboardScreen,
    })),
  recommendations: () =>
    import("../screens/RecommendationsScreen").then((module) => ({
      default: module.RecommendationsScreen,
    })),
  capture: () =>
    import("../screens/CaptureScreen").then((module) => ({
      default: module.CaptureScreen,
    })),
  import: () =>
    import("../screens/ImportScreen").then((module) => ({
      default: module.ImportScreen,
    })),
  "journal-tray": () =>
    import("../screens/JournalTrayScreen").then((module) => ({
      default: module.JournalTrayScreen,
    })),
  income: () =>
    import("../screens/IncomeScreen").then((module) => ({
      default: module.IncomeScreen,
    })),
  "sales-documents": () =>
    import("../screens/SalesDocumentsScreen").then((module) => ({
      default: module.SalesDocumentsScreen,
    })),
  kakebo: () =>
    import("../screens/KakeboScreen").then((module) => ({
      default: module.KakeboScreen,
    })),
  books: () =>
    import("../screens/BooksScreen").then((module) => ({
      default: module.BooksScreen,
    })),
  evidence: () =>
    import("../screens/EvidenceScreen").then((module) => ({
      default: module.EvidenceScreen,
    })),
  remittances: () =>
    import("../screens/RemittancesScreen").then((module) => ({
      default: module.RemittancesScreen,
    })),
  "deduction-wizard": () =>
    import("../screens/DeductionWizardScreen").then((module) => ({
      default: module.DeductionWizardScreen,
    })),
  filing: () =>
    import("../screens/FilingScreen").then((module) => ({
      default: module.FilingScreen,
    })),
  "year-end": () =>
    import("../screens/YearEndScreen").then((module) => ({
      default: module.YearEndScreen,
    })),
  consumption: () =>
    import("../screens/ConsumptionScreen").then((module) => ({
      default: module.ConsumptionScreen,
    })),
  "past-filings": () =>
    import("../screens/PastFilingsScreen").then((module) => ({
      default: module.PastFilingsScreen,
    })),
  "kosei-seikyu": () =>
    import("../screens/KoseiSeikyuGuideScreen").then((module) => ({
      default: module.KoseiSeikyuGuideScreen,
    })),
  settings: () =>
    import("../screens/SettingsScreen").then((module) => ({
      default: module.SettingsScreen,
    })),
};

const LAZY_SCREENS = Object.fromEntries(
  Object.entries(SCREEN_LOADERS).map(([id, loader]) => [id, lazyScreen(loader)]),
) as Record<string, ReturnType<typeof lazyScreen>>;

export const LazyOnboardingScreen = lazy(() =>
  import("../screens/OnboardingScreen").then((module) => ({
    default: module.OnboardingScreen,
  })),
);

export function getLazyScreen(id: string) {
  return LAZY_SCREENS[id];
}

export function preloadScreen(id: string) {
  void SCREEN_LOADERS[id]?.().catch(() => undefined);
}

export function preloadOnboarding() {
  void import("../screens/OnboardingScreen").catch(() => undefined);
}
