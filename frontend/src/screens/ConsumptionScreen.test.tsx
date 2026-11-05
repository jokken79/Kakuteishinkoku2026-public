import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ConsumptionScreen } from "./ConsumptionScreen";

vi.mock("../lib/hooks", () => {
  const option = (method: string, label: string) => ({
    method, label, eligible: false, eligibility_status: "unverified",
    sales_tax: 1000, purchase_tax_credit: 500, national_tax: 500,
    local_tax: 100, total_tax: 600, note: null,
  });
  return {
    useTaxpayer: () => ({ data: { is_taxable_consumption: true } }),
    useConsumption: () => ({ data: {
      year: 2026, is_taxable: true, business_category: null, recommended: null,
      recommended_saving: 0,
      honsoku: option("honsoku", "本則課税"),
      kani: option("kani", "簡易課税"),
      tokurei: option("tokurei", "2割特例"),
      sales_breakdown: { taxable_sales_10: 0, taxable_sales_8: 0, national_tax_10: 0, national_tax_8: 0, national_tax_total: 0 },
      purchase_breakdown: { qualified_purchases_10: 0, qualified_purchases_8: 0, national_tax_10: 0, national_tax_8: 0, national_tax_total: 0, excluded_non_qualified: 1000 },
    } }),
  };
});

it("presenta escenarios sin recomendación y aclara el alcance del PDF", () => {
  render(<ConsumptionScreen />);
  expect(screen.getByText("Simulación: requisitos pendientes de comprobar")).toBeInTheDocument();
  expect(screen.getAllByText("Estimación · elegibilidad sin verificar")).toHaveLength(2);
  expect(screen.getByText("Falta seleccionar 事業区分")).toBeInTheDocument();
  expect(screen.getByText(/algunas pueden tener un crédito transitorio no calculado/)).toBeInTheDocument();
  expect(screen.getByText(/no en facturas verificadas/)).toBeInTheDocument();
  expect(screen.getByText(/No es un formulario oficial/)).toBeInTheDocument();
  expect(screen.queryByText("Método recomendado (el de menor pago)")).not.toBeInTheDocument();
});
