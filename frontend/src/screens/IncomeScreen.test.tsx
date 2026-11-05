import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { IncomeScreen } from "./IncomeScreen";

const mutations = vi.hoisted(() => ({ patch: vi.fn(), remove: vi.fn() }));
vi.mock("../lib/hooks", () => ({
  useIncomeSources: () => ({ data: { income_sources: [
    { id: "a", income_type: "kyuyo", gross: 2_000_000, withholding: 0, expenses: 0, meta: { label: "Empresa A" } },
    { id: "b", income_type: "kyuyo", gross: 3_000_000, withholding: 0, expenses: 0, meta: { label: "Empresa B" } },
  ], sales_revenue: 0, total_withholding: 0 } }),
  useActiveYearLock: () => ({ isReadOnly: false, label: "" }),
  useFilingDraft: () => ({}),
  useCreateIncomeSource: () => ({ mutate: vi.fn() }),
  usePatchIncomeSource: () => ({ mutate: mutations.patch }),
  useDeleteIncomeSource: () => ({ mutate: mutations.remove }),
}));

it("muestra ambas nóminas y permite abrir una nueva fuente opcional", () => {
  render(<IncomeScreen />);
  expect(screen.getByText(/登録済み・¥2,000,000/)).toBeInTheDocument();
  expect(screen.getByText(/登録済み・¥3,000,000/)).toBeInTheDocument();
  expect(screen.getAllByText(/Empresa A/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/Empresa B/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: /＋ 雑所得/ }));
  expect(screen.getByLabelText(/雑所得の収入金額/)).toBeInTheDocument();
});

it("requiere confirmación para modificar o eliminar una fuente", () => {
  mutations.patch.mockClear();
  mutations.remove.mockClear();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<IncomeScreen />);
  fireEvent.click(screen.getByRole("button", { name: /Empresa A.*登録済み/ }));
  fireEvent.change(screen.getByDisplayValue("Empresa A"), { target: { value: "Empresa nueva" } });
  fireEvent.click(screen.getByRole("button", { name: "更新する" }));
  fireEvent.click(screen.getByRole("button", { name: "削除" }));
  expect(mutations.patch).not.toHaveBeenCalled();
  expect(mutations.remove).not.toHaveBeenCalled();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "更新する" }));
  expect(mutations.patch).toHaveBeenCalledWith({
    id: "a", patch: { gross: 2_000_000, withholding: 0, expenses: 0, meta: { label: "Empresa nueva" } },
  });
  confirm.mockRestore();
});
