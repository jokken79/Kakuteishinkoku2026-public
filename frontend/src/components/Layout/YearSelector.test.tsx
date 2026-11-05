import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { YearSelector } from "./YearSelector";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("conserva el menú y permite reintentar cuando falla la creación", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((_url: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({
      active_year: 2025,
      years: [{ year: 2025, status: "open", rules_available: true }],
    }) });
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><YearSelector /></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: /年度の選択/ }));
  await waitFor(() => expect(screen.getByRole("option", { name: /2025/ })).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: /新しい年度を開始/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo abrir el año fiscal");
  expect(screen.getByRole("button", { name: /新しい年度を開始/ })).toBeEnabled();
  client.clear();
});
