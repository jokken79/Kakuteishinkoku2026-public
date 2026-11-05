import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RemittancesScreen } from "./RemittancesScreen";

vi.mock("../lib/store", () => ({ useUiStore: () => vi.fn() }));
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("permite corregir y descargar la lectura sin presentarla como comprobante", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({
    text: "Operación 123", warnings: [], empty_pages: [],
  }) }));
  const createUrl = vi.fn().mockReturnValue("blob:test");
  vi.stubGlobal("URL", { createObjectURL: createUrl, revokeObjectURL: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<RemittancesScreen />);
  fireEvent.change(screen.getByLabelText("Archivo del comprobante"), { target: { files: [new File(["x"], "comprobante.pdf", { type: "application/pdf" })] } });
  fireEvent.click(screen.getByRole("button", { name: "Leer documento" }));
  const text = await screen.findByLabelText("Texto extraído para revisar y corregir");
  fireEvent.change(text, { target: { value: "Operación corregida" } });
  fireEvent.click(screen.getByRole("button", { name: "Descargar texto para revisión" }));
  expect(createUrl).toHaveBeenCalledOnce();
  expect(click).toHaveBeenCalledOnce();
  expect(screen.getByRole("status")).toHaveTextContent("sin cifrar");
  expect(screen.getByText(/Este texto es editable y no sustituye/)).toBeInTheDocument();
});
