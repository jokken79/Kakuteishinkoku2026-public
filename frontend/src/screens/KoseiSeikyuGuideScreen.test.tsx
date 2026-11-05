import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { KoseiSeikyuGuideScreen } from "./KoseiSeikyuGuideScreen";

it("muestra la guía general sin calcular una devolución", () => {
  render(<KoseiSeikyuGuideScreen />);
  expect(screen.getByRole("link", { name: "国税庁の案内" })).toHaveAttribute("href", expect.stringContaining("nta.go.jp"));
  expect(screen.getByText(/還付額の確定を行いません/)).toBeInTheDocument();
});
