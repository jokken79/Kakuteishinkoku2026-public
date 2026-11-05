import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ApiError } from "../lib/api";
import { YearEndScreen } from "./YearEndScreen";

const state = vi.hoisted(() => ({ error: null as Error | null }));
vi.mock("../lib/hooks", () => ({
  useDeductions: () => ({ isError: true, error: state.error }),
  useYearEndProfile: () => ({ data: { name: "山田 太郎", name_kana: null, address: null } }),
}));

it("explica el ejercicio ausente y conserva el formulario manual", () => {
  state.error = new ApiError("No existe", 404, "no_fiscal_year");
  render(<YearEndScreen />);
  expect(screen.getByText(/El ejercicio 2026 todavía no está registrado/)).toBeInTheDocument();
  expect(screen.getByLabelText("Nombre completo *")).toBeEnabled();
  expect(screen.getByRole("button", { name: "Descargar borrador de 基礎控除" })).toBeEnabled();
});

it("no confunde otros fallos de consulta con un ejercicio inexistente", () => {
  state.error = new ApiError("Error", 500, "server_error");
  render(<YearEndScreen />);
  expect(screen.getByRole("alert")).toHaveTextContent("No se pudieron consultar las deducciones");
  expect(screen.queryByText(/El ejercicio 2026 todavía no está registrado/)).toBeNull();
});

it("advierte cuando el ingreso fiscal del familiar supera el límite de 2026", () => {
  state.error = new ApiError("No existe", 404, "no_fiscal_year");
  render(<YearEndScreen />);
  fireEvent.click(screen.getByLabelText("Incluir un familiar"));
  const income = screen.getByLabelText("Ingreso fiscal estimado en 2026, yenes");
  expect(screen.getByText(/Si recibe pensión o salario/)).toBeInTheDocument();
  fireEvent.change(income, { target: { value: "620000" } });
  expect(screen.queryByText(/El importe supera/)).not.toBeInTheDocument();
  fireEvent.change(income, { target: { value: "620001" } });
  expect(screen.getByRole("alert")).toHaveTextContent("¥620.000");
});
