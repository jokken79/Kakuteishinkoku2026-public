import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { DashboardScreen } from "./DashboardScreen";

const state = vi.hoisted(() => ({ error: false, navigate: vi.fn() }));
vi.mock("../lib/hooks", () => ({
  useActiveYear: () => 2025,
  usePendingReceipts: () => state.error ? { isError: true } : { data: [] },
  useRecommendations: () => ({}),
  useFilingDraft: () => state.error ? { isError: true } : { data: {
    is_refund: false, final_amount: 0, total_tax: 0, withholding_total: 0,
    total_income_deductions: 0,
    checklist: [
      { key: "journal_confirmed", label: "仕訳をすべて確認", done: true },
      { key: "forms_ready", label: "申告書の内容を確認", done: false, detail: "PDFは下書きです。" },
    ],
  } },
}));
vi.mock("../lib/store", () => ({ useUiStore: (selector: (s: { setActiveSection: typeof state.navigate }) => unknown) => selector({ setActiveSection: state.navigate }) }));

it("muestra las comprobaciones pendientes sin afirmar que la declaración está completa", () => {
  state.error = false;
  render(<DashboardScreen />);
  expect(screen.getByText(/申告書の内容を確認/)).toBeInTheDocument();
  expect(screen.getByText(/no confirma que la declaración esté completa ni presentada/)).toBeInTheDocument();
  expect(screen.queryByText("100%")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Ver declaración y lista completa/ }));
  expect(state.navigate).toHaveBeenCalledWith("filing");
});

it("avisa cuando no puede cargar los datos en lugar de mostrar cero", () => {
  state.error = true;
  render(<DashboardScreen />);
  expect(screen.getByText(/No se pudo cargar la estimación/)).toBeInTheDocument();
  expect(screen.getByText("No se pudo cargar")).toBeInTheDocument();
  expect(screen.getByText(/No se pudo cargar la lista/)).toBeInTheDocument();
});
