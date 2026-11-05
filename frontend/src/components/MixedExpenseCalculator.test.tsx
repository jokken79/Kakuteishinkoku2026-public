import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { MixedExpenseCalculator } from "./MixedExpenseCalculator";

it("calcula la parte profesional y no acepta kilómetros imposibles", () => {
  render(<MixedExpenseCalculator />);
  fireEvent.click(screen.getByText("Calcular uso mixto del coche · 家事按分"));
  fireEvent.change(screen.getByLabelText("Gasto a repartir (¥)"), { target: { value: "700000" } });
  fireEvent.change(screen.getByLabelText("Km de 副業"), { target: { value: "3000" } });
  fireEvent.change(screen.getByLabelText("Km totales"), { target: { value: "10000" } });
  expect(screen.getByRole("status")).toHaveTextContent("30.00 %");
  expect(screen.getByRole("status")).toHaveTextContent("210,000");
  expect(screen.getByRole("status")).toHaveTextContent("490,000");
  fireEvent.change(screen.getByLabelText("Km de 副業"), { target: { value: "10001" } });
  expect(screen.getByRole("status")).toHaveTextContent("no menores que los de 副業");
});
