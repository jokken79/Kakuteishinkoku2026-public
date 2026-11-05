import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { EstimatedPrepayment } from "./EstimatedPrepayment";

vi.mock("../lib/hooks", async (importOriginal) => ({
  ...await importOriginal<typeof import("../lib/hooks")>(),
  useActiveYearLock: () => ({ isReadOnly: false }),
}));
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("distingue el dato no informado de cero y pide confirmación antes de guardar", async () => {
  const request = vi.fn().mockImplementation((_url: string, options?: RequestInit) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve(options?.method === "PUT" ? { amount: 0 } : { amount: null }),
  }));
  vi.stubGlobal("fetch", request);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><EstimatedPrepayment year={2026} /></QueryClientProvider>);
  expect(await screen.findByText(/No informado/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/Importe notificado en 2026/), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Guardar importe" }));
  await waitFor(() => expect(screen.getByText(/Importe guardado/)).toBeInTheDocument());
  expect(window.confirm).toHaveBeenCalledOnce();
  const calls = request.mock.calls as [string, RequestInit?][];
  const put = calls.find((call) => call[1]?.method === "PUT");
  expect(put?.[1]?.body).toBe('{"amount":0}');
  client.clear();
});
