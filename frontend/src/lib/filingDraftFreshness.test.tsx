import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useFilingDraft } from "./hooks";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("oculta el resultado anterior durante una actualización y después de un error", async () => {
  let failRequest: (error: Error) => void = () => {};
  const pending = new Promise<never>((_resolve, reject) => { failRequest = reject; });
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ year: 2026, final_amount: 12345 }) })
    .mockReturnValueOnce(pending));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { result } = renderHook(() => useFilingDraft(2026), {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  await waitFor(() => expect(result.current.data?.final_amount).toBe(12345));
  let refresh: Promise<unknown> | undefined;
  act(() => { refresh = result.current.refetch(); });
  await waitFor(() => expect(result.current.data).toBeUndefined());
  await act(async () => { failRequest(new Error("offline")); await refresh; });
  await waitFor(() => expect(result.current.isError).toBe(true));
  expect(result.current.data).toBeUndefined();
  client.clear();
});
