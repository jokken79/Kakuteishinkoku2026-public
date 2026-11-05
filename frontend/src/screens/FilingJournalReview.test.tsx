import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ApiError } from "../lib/api";
import { FilingScreen } from "./FilingScreen";

vi.mock("../lib/hooks", () => ({
  useActiveYear: () => 2025,
  useActiveYearLock: () => ({ isReadOnly: false }),
  useFilingDraft: () => ({ isError: true, error: new ApiError("Revisar asientos", 409, "journal_origin_unknown"), refetch: vi.fn() }),
}));
vi.mock("../lib/store", () => ({ useUiStore: () => vi.fn() }));
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("muestra la revisión de asientos sin modificarlos", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ year: 2025,
    entries: [{ id: "prueba", fingerprint: "a".repeat(64), date: "2025-01-01", description: "Anterior", transaction_id: null,
      lines: [{ side: "debit", account_code: "101", account_name: "現金", amount: 1000 }] }],
  }) });
  vi.stubGlobal("fetch", fetchMock);
  render(<FilingScreen />);
  fireEvent.click(screen.getByRole("button", { name: "Ver asientos sin identificar" }));
  expect(await screen.findByText(/2025-01-01 · Anterior/)).toBeInTheDocument();
  expect(screen.getByText(/101 現金 · ¥1,000/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/filing/journal-review?year=2025", { cache: "no-store" });
  const button = screen.getByRole("button", { name: "Conservar como manual" });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /He hecho una copia/ }));
  vi.spyOn(window, "confirm").mockReturnValue(false);
  fireEvent.click(button);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  vi.mocked(window.confirm).mockReturnValue(true);
  fireEvent.click(button);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(await screen.findByText(/No quedan asientos sin identificar/)).toBeInTheDocument();
});
