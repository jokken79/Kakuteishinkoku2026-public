import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { DependentsManager } from "./DependentsManager";

const classify = vi.hoisted(() => vi.fn().mockResolvedValue({ dependents: [] }));
const state = vi.hoisted(() => ({ year: 2026, loaded: true, legacy: false }));
const save = vi.hoisted(() => vi.fn());
vi.mock("../lib/api", () => ({ classifyDependents: classify }));
vi.mock("../lib/hooks", () => ({
  useActiveYear: () => state.year,
  useDeductions: () => ({ data: state.loaded ? { year: state.year, deductions: state.legacy
    ? [{ id: "legacy", type: "fuyo", amount: 480000, meta: { kind: "elderly", count: 1 } }] : [] } : undefined }),
  useCreateDeduction: () => ({ mutate: save }),
  usePatchDeduction: () => ({ mutate: vi.fn() }),
  useDeleteDeduction: () => ({ mutate: vi.fn() }),
}));

it("distingue ingresos desconocidos de cero confirmado", async () => {
  state.year = 2026;
  state.loaded = true;
  classify.mockClear();
  render(<DependentsManager />);
  fireEvent.click(screen.getByRole("button", { name: /扶養家族を追加/ }));
  const expected = { name: "（無名）", relationship: null, birth_date: null, goukei_shotoku: null,
    residence: "domestic", country: null, cohabitation: "together", eligible_cohabiting_ancestor: null, overseas_exemption: null,
    annual_remittance: null };
  await waitFor(() => expect(classify).toHaveBeenCalledWith(2026, [expected]));
  const amount = screen.getByPlaceholderText("例：0");
  fireEvent.change(amount, { target: { value: "0" } });
  await waitFor(() => expect(classify).toHaveBeenLastCalledWith(2026, [{ ...expected, goukei_shotoku: 0 }]));
  expect(amount).toHaveValue("0");
});

it("no guarda importes desactualizados mientras se recalcula", async () => {
  state.year = 2026;
  state.loaded = true;
  save.mockClear();
  let resolveResult: (value: { dependents: { income_tax_amount: number; kind_label: string; qualifies: boolean }[] }) => void = () => {};
  classify.mockImplementationOnce(() => new Promise((resolve) => { resolveResult = resolve; }));
  render(<DependentsManager />);
  fireEvent.click(screen.getByRole("button", { name: /扶養家族を追加/ }));
  const button = screen.getByRole("button", { name: "扶養家族を保存" });
  expect(button).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("Calculando");
  await act(async () => { resolveResult({ dependents: [{ income_tax_amount: 380000, kind_label: "一般", qualifies: true }] }); await Promise.resolve(); });
  expect(button).toBeEnabled();
  fireEvent.click(button);
  expect(save).toHaveBeenCalledOnce();
});

it("bloquea el guardado si falla la clasificación y permite reintentar", async () => {
  state.year = 2026;
  state.loaded = true;
  classify.mockRejectedValueOnce(new Error("sin conexión"));
  classify.mockResolvedValueOnce({ dependents: [{ income_tax_amount: 0, kind_label: "要確認", qualifies: false }] });
  render(<DependentsManager />);
  fireEvent.click(screen.getByRole("button", { name: /扶養家族を追加/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo calcular");
  const saveButton = screen.getByRole("button", { name: "扶養家族を保存" });
  expect(saveButton).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
  await waitFor(() => expect(saveButton).toBeEnabled());
});

it("descarta el borrador anterior y bloquea la edición mientras carga otro año", () => {
  state.year = 2025;
  state.loaded = true;
  const view = render(<DependentsManager />);
  fireEvent.click(screen.getByRole("button", { name: /扶養家族を追加/ }));
  fireEvent.change(screen.getByPlaceholderText("例：架空 花子"), { target: { value: "Familiar 2025" } });
  state.year = 2026;
  state.loaded = false;
  view.rerender(<DependentsManager />);
  expect(screen.queryByDisplayValue("Familiar 2025")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /扶養家族を追加/ })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("2026");
  state.loaded = true;
  view.rerender(<DependentsManager />);
  expect(screen.getByRole("button", { name: /扶養家族を追加/ })).toBeEnabled();
  expect(screen.queryByDisplayValue("Familiar 2025")).not.toBeInTheDocument();
});

it("solicita el importe anual para la excepción por remesas", async () => {
  state.year = 2026;
  state.loaded = true;
  render(<DependentsManager />);
  fireEvent.click(screen.getByRole("button", { name: /扶養家族を追加/ }));
  fireEvent.click(screen.getByRole("button", { name: /^国外（海外）$/ }));
  fireEvent.change(screen.getByDisplayValue("なし"), { target: { value: "remittance_380k" } });
  const amount = screen.getByLabelText(/Envíos de este año a este familiar/);
  fireEvent.change(amount, { target: { value: "380000" } });
  expect(amount).toHaveValue(380000);
  await waitFor(() => expect(classify).toHaveBeenLastCalledWith(2026, [{
    name: "（無名）", relationship: null, birth_date: null, goukei_shotoku: null,
    residence: "overseas", country: null, cohabitation: "together", eligible_cohabiting_ancestor: null,
    overseas_exemption: "remittance_380k", annual_remittance: 380000,
  }]));
});

it("protege el registro antiguo hasta que se prepare expresamente su sustitución", () => {
  state.year = 2026;
  state.loaded = true;
  state.legacy = true;
  render(<DependentsManager />);
  expect(screen.getByRole("alert")).toHaveTextContent("formato antiguo");
  expect(screen.getByRole("button", { name: /扶養家族を追加/ })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "扶養家族を保存" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Preparar sustitución/ }));
  expect(screen.getByRole("button", { name: /扶養家族を追加/ })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "扶養家族を保存" })).not.toBeInTheDocument();
  state.legacy = false;
});

it("permite confirmar explícitamente los requisitos de 同居老親等", async () => {
  state.year = 2026;
  state.loaded = true;
  render(<DependentsManager />);
  fireEvent.click(screen.getByRole("button", { name: /扶養家族を追加/ }));
  const field = screen.getByLabelText(/cumple los requisitos de 同居老親等/);
  fireEvent.change(field, { target: { value: "true" } });
  expect(field).toHaveValue("true");
  await waitFor(() => expect(classify).toHaveBeenLastCalledWith(2026, [{
    name: "（無名）", relationship: null, birth_date: null, goukei_shotoku: null,
    residence: "domestic", country: null, cohabitation: "together",
    eligible_cohabiting_ancestor: true, overseas_exemption: null, annual_remittance: null,
  }]));
});
