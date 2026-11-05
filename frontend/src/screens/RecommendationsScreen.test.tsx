import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RecommendationsScreen } from "./RecommendationsScreen";

vi.mock("../lib/hooks", () => ({ useRecommendations: () => ({ data: {
  actionable_count: 1, total_estimated_saving: 999999,
  recommendations: [{ id: "example", category: "info", priority: "alta", status: "actionable",
    title_jp: "確認", body_jp: "条件を確認", body_es: "Revisa las condiciones",
    income_tax_saving: 0, resident_tax_saving: 0, total_saving: 0 }],
} }) }));
vi.mock("../lib/store", () => ({ useUiStore: () => vi.fn() }));

it("no presenta la suma de escenarios como ahorro disponible", () => {
  render(<RecommendationsScreen />);
  expect(screen.getByText(/no deben sumarse como ahorro total/)).toBeInTheDocument();
  expect(screen.queryByText(/999,999/)).not.toBeInTheDocument();
  expect(screen.getByText(/Revisar condiciones/)).toBeInTheDocument();
});
