import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FilingTypeByYear } from "./FilingTypeByYear";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function renderWithClient(element: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}>{element}</QueryClientProvider>) };
}

it("exige selección y copia de seguridad y permite cancelar antes de guardar", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true, json: () => Promise.resolve({ value: "aoiro_65", source: "profile_unconfirmed" }),
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(window, "confirm").mockReturnValue(false);
  renderWithClient(<FilingTypeByYear year={2026} readOnly={false} onSaved={vi.fn()} />);
  expect(await screen.findByText(/Heredada del perfil/)).toBeInTheDocument();
  const button = screen.getByRole("button", { name: "Guardar modalidad de 2026" });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Elegir modalidad para 2026"), { target: { value: "shiroiro" } });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/He hecho una copia de seguridad/));
  fireEvent.click(button);
  expect(window.confirm).toHaveBeenCalled();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("guarda solo el año indicado después de confirmar", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ value: "aoiro_65", source: "profile_unconfirmed" }) })
    .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ value: "shiroiro", source: "year" }) });
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const onSaved = vi.fn();
  const { client } = renderWithClient(<FilingTypeByYear year={2026} readOnly={false} onSaved={onSaved} />);
  const invalidate = vi.spyOn(client, "invalidateQueries");
  await screen.findByText(/Heredada del perfil/);
  fireEvent.change(screen.getByLabelText("Elegir modalidad para 2026"), { target: { value: "shiroiro" } });
  fireEvent.click(screen.getByLabelText(/He hecho una copia de seguridad/));
  fireEvent.click(screen.getByRole("button", { name: "Guardar modalidad de 2026" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
  expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/fiscal-years/2026/filing-type");
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["recommendations", 2026] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["deductions", "suggestions", 2026] });
  expect(screen.getByText(/Confirmada para este año/)).toBeInTheDocument();
});
