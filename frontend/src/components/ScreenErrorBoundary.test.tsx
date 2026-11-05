import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ScreenErrorBoundary } from "./ScreenErrorBoundary";

afterEach(() => vi.restoreAllMocks());

it("mantiene la navegación y permite cambiar de sección si falla una pantalla", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  function BrokenScreen(): never { throw new Error("Failed to fetch dynamically imported module"); }
  function Shell() {
    return <><nav>Menú disponible</nav><ScreenErrorBoundary><BrokenScreen /></ScreenErrorBoundary></>;
  }
  const view = render(<Shell />);
  expect(screen.getByRole("alert")).toHaveTextContent("No se pudo abrir esta pantalla");
  expect(screen.getByText(/cambios que aún no hayas guardado/)).toBeInTheDocument();
  expect(screen.getByText("Menú disponible")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Recargar aplicación" })).toBeInTheDocument();
  view.rerender(<><nav>Menú disponible</nav><ScreenErrorBoundary key="otra"><p>Otra sección</p></ScreenErrorBoundary></>);
  expect(screen.getByText("Otra sección")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
