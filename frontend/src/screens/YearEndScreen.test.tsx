import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { YearEndScreen } from "./YearEndScreen";

vi.mock("../lib/hooks", () => ({
  useDeductions: () => ({ data: { deductions: [
    { type: "disability_self" },
    { type: "fuyo", meta: { dependents: [{ name: "山田 花子", relationship: "母", birth_date: "1954-04-07", goukei_shotoku: 0, residence: "domestic" }] } },
  ] } }),
  useYearEndProfile: () => ({ data: { name: "山田 太郎", name_kana: "ヤマダ タロウ", address: "愛知県名古屋市" } }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("carga datos guardados sin reemplazar texto escrito", () => {
  render(<YearEndScreen />);
  fireEvent.change(screen.getByLabelText("Nombre completo *"), { target: { value: "Nombre manual" } });
  fireEvent.click(screen.getByRole("button", { name: "Cargar datos registrados de 2026" }));
  expect(screen.getByLabelText("Nombre completo *")).toHaveValue("Nombre manual");
  expect(screen.getAllByLabelText("Nombre en カタカナ")[0]).toHaveValue("ヤマダ タロウ");
  expect(screen.getByLabelText("Dirección actual")).toHaveValue("愛知県名古屋市");
  expect(screen.getByLabelText("Nombre del familiar *")).toHaveValue("山田 花子");
  expect(screen.getByLabelText("Ingreso fiscal estimado en 2026, yenes")).toHaveValue(0);
  expect(screen.getByLabelText("Solicito la categoría ordinaria para mí")).toBeChecked();
});

it("genera un borrador con el familiar y discapacidad elegidos", async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, blob: () => Promise.resolve(new Blob()) });
  vi.stubGlobal("fetch", request);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<YearEndScreen />);

  fireEvent.change(screen.getByLabelText("Nombre completo *"), { target: { value: "山田 太郎" } });
  fireEvent.click(screen.getByLabelText("Incluir un familiar"));
  fireEvent.change(screen.getByLabelText("Nombre del familiar *"), { target: { value: "山田 花子" } });
  fireEvent.change(screen.getByLabelText("Ingreso fiscal estimado en 2026, yenes"), { target: { value: "0" } });
  fireEvent.click(screen.getByLabelText("Solicito la categoría ordinaria para mí"));
  fireEvent.click(screen.getByRole("button", { name: "Descargar PDF oficial para revisar" }));

  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("PDF de revisión descargado"));
  expect(request).toHaveBeenCalledOnce();
  const options = request.mock.calls[0][1] as RequestInit;
  const payload = JSON.parse(options.body as string) as { dependent: { income_estimate: number }; disability: string };
  expect(payload.dependent.income_estimate).toBe(0);
  expect(payload.disability).toBe("ordinary");
});

it("no supone que el ingreso del 副業 sea cero en el borrador de 基礎控除", async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, blob: () => Promise.resolve(new Blob()) });
  vi.stubGlobal("fetch", request);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<YearEndScreen />);
  fireEvent.change(screen.getByLabelText("Nombre completo *"), { target: { value: "山田 太郎" } });
  fireEvent.change(screen.getByLabelText("Salario bruto anual estimado (¥)"), { target: { value: "5000000" } });
  fireEvent.click(screen.getByRole("button", { name: "Descargar borrador de 基礎控除" }));
  await waitFor(() => expect(request).toHaveBeenCalledOnce());
  const options = request.mock.calls[0][1] as RequestInit;
  const payload = JSON.parse(options.body as string) as { salary_revenue: number; other_income: number | null; complete_income_estimate: boolean };
  expect(payload.salary_revenue).toBe(5_000_000);
  expect(payload.other_income).toBeNull();
  expect(payload.complete_income_estimate).toBe(false);
});
