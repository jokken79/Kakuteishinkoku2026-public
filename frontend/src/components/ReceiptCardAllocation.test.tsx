import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReceiptCard } from "./ReceiptCard";
import type { Transaction } from "../lib/api";

afterEach(() => vi.restoreAllMocks());

it("guarda el reparto con confirmación conservando el total del recibo", async () => {
  const tx: Transaction = {
    id: "test-id", date: "2025-01-01", vendor: "Taller ficticio", total_amount: 700000,
    registration_number: null, is_qualified_invoice: false, confidence: null,
    status: "pending", tax_lines: [], evidence_id: null, account_code: "599",
    field_confidences: null,
  };
  const save = vi.fn().mockResolvedValue(undefined);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ReceiptCard tx={tx} selected={false} onToggleSelect={() => {}} onConfirm={() => Promise.resolve()} onAllocation={save} />);
  fireEvent.click(screen.getByText("Repartir gasto mixto por kilómetros"));
  fireEvent.change(screen.getByLabelText("Km de 副業"), { target: { value: "3000" } });
  fireEvent.change(screen.getByLabelText("Km totales"), { target: { value: "10000" } });
  fireEvent.change(screen.getByLabelText("Criterio y período"), { target: { value: "Registro de viajes 2025" } });
  vi.mocked(window.confirm).mockReturnValueOnce(false);
  fireEvent.click(screen.getByRole("button", { name: "Guardar reparto" }));
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Guardar reparto" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith("test-id", {
    expected_total: 700000, numerator: 3000, denominator: 10000, rationale: "Registro de viajes 2025",
  }));
  expect(window.confirm).toHaveBeenCalledTimes(2);
});

it("explica el importe completo y no confirma si se cancela", () => {
  const tx: Transaction = {
    id: "test-id", date: "2025-01-01", vendor: "Taller ficticio", total_amount: 700000,
    registration_number: null, is_qualified_invoice: false, confidence: null,
    status: "pending", tax_lines: [], evidence_id: null, account_code: "599",
    field_confidences: null,
  };
  const confirmReceipt = vi.fn().mockResolvedValue(undefined);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<ReceiptCard tx={tx} selected={false} onToggleSelect={() => {}} onConfirm={confirmReceipt} />);
  expect(screen.getByText(/confirmar incluirá el importe íntegro/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Taller ficticioを確認して承認/ }));
  expect(confirm).toHaveBeenCalledOnce();
  expect(confirmReceipt).not.toHaveBeenCalled();
});

it("muestra la parte profesional guardada antes de confirmar", () => {
  const tx: Transaction = {
    id: "test-id", date: "2025-01-01", vendor: "Taller ficticio", total_amount: 700000,
    registration_number: null, is_qualified_invoice: false, confidence: null,
    status: "pending", tax_lines: [], evidence_id: null, account_code: "599",
    field_confidences: null,
    business_allocation: { original_total: 700000, numerator: 3, denominator: 10, rationale: "viajes" },
  };
  render(<ReceiptCard tx={tx} selected={false} onToggleSelect={() => {}} onConfirm={() => Promise.resolve()} />);
  expect(screen.getByText(/Importe profesional según reparto guardado: ¥210,000/)).toBeInTheDocument();
});

it("presenta el indicador de factura como pendiente de verificación", () => {
  const tx: Transaction = {
    id: "test-id", date: "2025-01-01", vendor: "Comercio ficticio", total_amount: 1000,
    registration_number: "T1234567890123", is_qualified_invoice: true, confidence: 0.9,
    status: "pending", tax_lines: [], evidence_id: null, account_code: "599",
    field_confidences: null,
  };
  render(<ReceiptCard tx={tx} selected={false} onToggleSelect={() => {}} onConfirm={() => Promise.resolve()} />);
  expect(screen.getByText(/インボイス候補（未検証）/)).toBeInTheDocument();
  expect(screen.getByText(/no verifica el registro, la identidad ni la factura/)).toBeInTheDocument();
  expect(screen.getByText(/T1234567890123/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /sitio de 国税庁/ })).toHaveAttribute("href", "https://www.invoice-kohyo.nta.go.jp/");
});

it("muestra el número incluso si el indicador no pasó la comprobación", () => {
  const tx: Transaction = {
    id: "test-id", date: "2025-01-01", vendor: "Comercio ficticio", total_amount: 1000,
    registration_number: "T0000000000000", is_qualified_invoice: false, confidence: 0.5,
    status: "pending", tax_lines: [], evidence_id: null, account_code: "599",
    field_confidences: null,
  };
  render(<ReceiptCard tx={tx} selected={false} onToggleSelect={() => {}} onConfirm={() => Promise.resolve()} />);
  expect(screen.getByText(/T0000000000000/)).toBeInTheDocument();
  expect(screen.getByText(/el OCR puede equivocarse/)).toBeInTheDocument();
  expect(screen.queryByText(/インボイス候補（未検証）/)).not.toBeInTheDocument();
});

it("corrige el número solo tras confirmación", async () => {
  const tx: Transaction = {
    id: "test-id", date: "2025-01-01", vendor: "Comercio ficticio", total_amount: 1000,
    registration_number: null, is_qualified_invoice: false, confidence: 0.5,
    status: "pending", tax_lines: [], evidence_id: null, account_code: "599",
    field_confidences: null,
  };
  const save = vi.fn().mockResolvedValue(undefined);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<ReceiptCard tx={tx} selected={false} onToggleSelect={() => {}} onConfirm={() => Promise.resolve()} onRegistrationChange={save} />);
  fireEvent.click(screen.getByText("Corregir 登録番号 leído"));
  fireEvent.change(screen.getByLabelText("Número del documento (T + 13 dígitos)"), { target: { value: "t1234567890123" } });
  fireEvent.click(screen.getByRole("button", { name: "Guardar número corregido" }));
  expect(save).not.toHaveBeenCalled();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Guardar número corregido" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith("test-id", null, "T1234567890123"));
});

it("espera a que se guarde la categoría antes de permitir confirmar", async () => {
  const tx: Transaction = {
    id: "test-id", date: "2025-01-01", vendor: "Taller ficticio", total_amount: 700000,
    registration_number: null, is_qualified_invoice: false, confidence: null,
    status: "pending", tax_lines: [], evidence_id: null, account_code: "599",
    field_confidences: null,
  };
  let finish: () => void = () => {};
  const save = vi.fn().mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ReceiptCard tx={tx} selected={false} onToggleSelect={() => {}} onConfirm={() => Promise.resolve()} onAccountChange={save} />);
  fireEvent.change(screen.getByRole("combobox", { name: "カテゴリを選択" }), { target: { value: "501" } });
  expect(save).toHaveBeenCalledWith("test-id", "501");
  expect(screen.getByRole("button", { name: /Taller ficticioを確認して承認/ })).toBeDisabled();
  finish();
  await waitFor(() => expect(screen.getByRole("combobox", { name: "カテゴリを選択" })).toHaveValue("501"));
  expect(screen.getByRole("button", { name: /Taller ficticioを確認して承認/ })).toBeEnabled();
});

it("mantiene la categoría anterior si falla el guardado", async () => {
  const tx: Transaction = {
    id: "test-id", date: "2025-01-01", vendor: "Taller ficticio", total_amount: 700000,
    registration_number: null, is_qualified_invoice: false, confidence: null,
    status: "pending", tax_lines: [], evidence_id: null, account_code: "599",
    field_confidences: null,
  };
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ReceiptCard tx={tx} selected={false} onToggleSelect={() => {}} onConfirm={() => Promise.resolve()} onAccountChange={() => Promise.reject(new Error("offline"))} />);
  fireEvent.change(screen.getByRole("combobox", { name: "カテゴリを選択" }), { target: { value: "501" } });
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo guardar la categoría");
  expect(screen.getByRole("combobox", { name: "カテゴリを選択" })).toHaveValue("599");
});
