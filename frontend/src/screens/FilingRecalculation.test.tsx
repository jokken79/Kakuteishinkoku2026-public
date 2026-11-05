import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { FilingScreen } from "./FilingScreen";

const state = vi.hoisted(() => ({ refetch: vi.fn() }));
vi.mock("../lib/hooks", () => ({
  useActiveYear: () => 2026,
  useActiveYearLock: () => ({ isReadOnly: false }),
  useFilingDraft: () => ({
    data: {
      year: 2026, draft_id: "demo", filing_type: "aoiro_65", aoiro_deduction: 0,
      is_refund: false, final_amount: 100, business_income: 0, total_income: 0,
      total_income_deductions: 0, taxable_income: 0, income_tax_base: 0,
      reconstruction_tax: 0, total_tax: 0, withholding_total: 0,
      confirmed_count: 0, pending_count: 0, confirmed_expense_total: 0,
      income_breakdown: [], deductions_applied: [], checklist: [], bs_balanced: true,
      resident_tax: { total: 0, total_income: 0, taxable_income: 0, shotokuwari_prefectural: 0,
        shotokuwari_municipal: 0, shotokuwari_total: 0, kintowari_total: 0,
        chosei_kojo: 0, kintowari_prefectural: 0, kintowari_municipal: 0,
        forest_environment_tax: 0 },
    },
    isLoading: false, isError: false, refetch: state.refetch,
  }),
}));
vi.mock("../lib/store", () => ({ useUiStore: () => vi.fn() }));
vi.mock("../components/EstimatedPrepayment", () => ({ EstimatedPrepayment: () => null }));
vi.mock("../components/FilingTypeByYear", () => ({
  FilingTypeByYear: ({ onSaved }: { onSaved: () => void }) => <button onClick={onSaved}>Cambio guardado</button>,
}));

it("oculta el cálculo anterior si falla el recálculo y permite reintentarlo", async () => {
  state.refetch.mockReset()
    .mockResolvedValueOnce({ isError: true })
    .mockResolvedValueOnce({ isError: false, data: { year: 2026 } });
  render(<FilingScreen />);
  expect(screen.getByText("申告内容の確認")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cambio guardado" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("cálculo anterior ya no es válido");
  expect(screen.queryByText("申告内容の確認")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Volver a calcular" }));
  await waitFor(() => expect(screen.getByText("申告内容の確認")).toBeInTheDocument());
});
