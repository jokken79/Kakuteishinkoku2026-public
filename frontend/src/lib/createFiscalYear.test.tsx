import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useCreateFiscalYear } from "./hooks";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("actualiza las consultas de 2026 después de abrir el ejercicio", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ year: 2026, rules_available: true }),
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useCreateFiscalYear(), {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  await act(async () => { await result.current.mutateAsync(2026); });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deductions", 2026] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["year-end-profile", 2026] });
  client.clear();
});
