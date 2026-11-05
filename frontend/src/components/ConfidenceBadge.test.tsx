import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfidenceBadge } from "./ConfidenceBadge";

describe("ConfidenceBadge", () => {
  it("muestra 高信頼 y el % para score alto", () => {
    render(<ConfidenceBadge score={0.92} />);
    expect(screen.getByText("高信頼")).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();
  });

  it("muestra 要確認 para score bajo (< 0.75)", () => {
    render(<ConfidenceBadge score={0.4} />);
    expect(screen.getByText("要確認")).toBeInTheDocument();
  });

  it("muestra badge CSV neutro cuando no hay score", () => {
    render(<ConfidenceBadge score={null} />);
    expect(screen.getByText("CSV取込")).toBeInTheDocument();
  });

  it("en modo compacto solo muestra el % (sin etiqueta)", () => {
    render(<ConfidenceBadge score={0.92} compact />);
    expect(screen.getByText("92%")).toBeInTheDocument();
    expect(screen.queryByText("高信頼")).not.toBeInTheDocument();
  });
});
