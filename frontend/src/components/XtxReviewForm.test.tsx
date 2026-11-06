import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { XtxReviewForm } from "./XtxReviewForm";

const context = {
  year: 2025, name: "Synthetic Taxpayer", address: "Synthetic Address", office_code: "06127",
  name_kana: "サンプル", postal_code: "0000000", occupation: "翻訳",
  sales_revenue: 100, salary_revenue: 0, withholding: 10,
  social_insurance: 0, ideco: 0, life_insurance: 0, earthquake_insurance: 0,
};
const blocked = { schema_valid: true, ready_for_submission: false, missing: ["official_import_acceptance"] };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Introducir identidad y detalles XTX" }));
  await screen.findByLabelText("利用者識別番号 · 16 dígitos");
  fireEvent.change(screen.getByLabelText("利用者識別番号 · 16 dígitos"), { target: { value: "1234567890123456" } });
}
it("revisa sin almacenamiento persistente y mantiene bloqueado un XSD válido incompleto", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(context) })
    .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(blocked) });
  vi.stubGlobal("fetch", fetcher);
  const storage = vi.spyOn(Storage.prototype, "setItem");
  render(<XtxReviewForm draftId="synthetic" />);
  await open();
  expect(screen.getByRole("button", { name: /Descargar XTX/ })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Revisar XTX" }));
  expect(await screen.findByRole("status")).toHaveTextContent("XSD oficial: válido");
  expect(screen.getByRole("button", { name: /Descargar XTX/ })).toBeDisabled();
  expect(storage).not.toHaveBeenCalled();
  const init = fetcher.mock.calls[1][1] as RequestInit;
  expect(init.method).toBe("POST"); expect(init.cache).toBe("no-store");
  const body = JSON.parse(init.body as string) as { identity: { user_id: string }; details: { opening_balances: unknown; monthly_sales: unknown } };
  expect(body.identity.user_id).toBe("1234567890123456");
  expect(body.details.opening_balances).toBeNull(); expect(body.details.monthly_sales).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Cerrar y vaciar los datos XTX" }));
  expect(screen.queryByDisplayValue("1234567890123456")).not.toBeInTheDocument();
  fetcher.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(context) });
  fireEvent.click(screen.getByRole("button", { name: "Introducir identidad y detalles XTX" }));
  expect(await screen.findByLabelText("利用者識別番号 · 16 dígitos")).toHaveValue("");
});
it("descarta una revisión que llega después de editar los datos", async () => {
  let resolveReview!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(context) })
    .mockImplementationOnce(() => new Promise(resolve => { resolveReview = resolve; })));
  render(<XtxReviewForm draftId="synthetic" />); await open();
  fireEvent.click(screen.getByRole("button", { name: "Revisar XTX" }));
  fireEvent.change(screen.getByLabelText("マイナンバー · 12 dígitos"), { target: { value: "000000000000" } });
  await act(async () => { resolveReview({ ok: true, json: () => Promise.resolve({ ...blocked, ready_for_submission: true }) }); await Promise.resolve(); });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Descargar XTX/ })).toBeDisabled();
});
it("no convierte importes desconocidos en cero y borra identidad al cambiar de borrador", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(context) });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<XtxReviewForm draftId="first" />); await open();
  fireEvent.change(screen.getByLabelText("Pagador 1"), { target: { value: "Synthetic Customer" } });
  fireEvent.click(screen.getByRole("button", { name: "Revisar XTX" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("yenes enteros");
  expect(fetcher).toHaveBeenCalledTimes(1);
  view.rerender(<XtxReviewForm draftId="second" />);
  await waitFor(() => expect(screen.getByLabelText("利用者識別番号 · 16 dígitos")).toHaveValue(""));
});
