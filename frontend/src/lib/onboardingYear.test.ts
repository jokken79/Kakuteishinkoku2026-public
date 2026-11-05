import { afterEach, expect, it, vi } from "vitest";
import { completeOnboarding } from "./api";

afterEach(() => vi.unstubAllGlobals());

it("envía el ejercicio seleccionado al completar la configuración", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true, status: 200,
    json: () => Promise.resolve({ onboarded: true, year: 2026 }),
  });
  vi.stubGlobal("fetch", fetchMock);
  await completeOnboarding({ filing_type: "shiroiro" }, 2026);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/onboarding/complete?year=2026");
});
