import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SideBusinessEstimate } from "./SideBusinessEstimate";

afterEach(() => vi.restoreAllMocks());

describe("orientación del 副業", () => {
  it("distingue importes vacíos de cero y muestra una pérdida sin aplicarla al salario", () => {
    render(<SideBusinessEstimate />);
    fireEvent.click(screen.getByText("Calcular una orientación para mi 副業"));
    const income = screen.getByLabelText("Ingresos de la actividad en 2026 (¥)");
    const expenses = screen.getByLabelText("Gastos atribuibles a la actividad en 2026 (¥)");
    fireEvent.change(expenses, { target: { value: "700000" } });
    expect(screen.queryByRole("status")).toBeNull();
    fireEvent.change(income, { target: { value: "0" } });
    expect(screen.getByRole("status")).toHaveTextContent("pérdida ¥700,000");
    expect(screen.getByText(/una pérdida de 雑所得 no se resta del salario/)).toBeInTheDocument();
    fireEvent.change(income, { target: { value: "800000" } });
    expect(screen.getByRole("status")).toHaveTextContent("beneficio ¥100,000");
  });

  it("permite usar la parte profesional sin sumar otros gastos automáticamente", () => {
    render(<SideBusinessEstimate />);
    fireEvent.click(screen.getByText("Calcular una orientación para mi 副業"));
    fireEvent.click(screen.getByText("Calcular uso mixto del coche · 家事按分"));
    fireEvent.change(screen.getByLabelText("Gasto a repartir (¥)"), { target: { value: "700000" } });
    fireEvent.change(screen.getByLabelText("Km de 副業"), { target: { value: "3000" } });
    fireEvent.change(screen.getByLabelText("Km totales"), { target: { value: "10000" } });
    fireEvent.click(screen.getByRole("button", { name: "Usar esta parte como total de gastos del cálculo" }));
    expect(screen.getByLabelText("Gastos atribuibles a la actividad en 2026 (¥)")).toHaveValue(210000);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.change(screen.getByLabelText("Gasto a repartir (¥)"), { target: { value: "800000" } });
    fireEvent.click(screen.getByRole("button", { name: "Usar esta parte como total de gastos del cálculo" }));
    expect(confirm).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("Gastos atribuibles a la actividad en 2026 (¥)")).toHaveValue(210000);
  });
});
