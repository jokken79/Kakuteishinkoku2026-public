import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DownloadRow } from "./FilingScreen";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("explica si falta el formulario oficial sin descargar una réplica", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false,
    json: () => Promise.resolve({ detail: { code: "official_template_missing" } }),
  }));
  const download = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<DownloadRow href="/test" icon="file" title="申告書" desc="PDF" tag="PDF" />);
  fireEvent.click(screen.getByRole("button", { name: /申告書/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Falta la plantilla oficial");
  expect(download).not.toHaveBeenCalled();
});

it("explica que falta reconocer la oficina fiscal antes de generar XTX", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false,
    json: () => Promise.resolve({ detail: { code: "tax_office_unrecognized" } }),
  }));
  render(<DownloadRow href="/test" icon="file" title="e-Tax" desc="Datos" tag="XTX" />);
  fireEvent.click(screen.getByRole("button", { name: /e-Tax/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("oficina fiscal");
});

it("descarga el archivo usando el nombre del servidor", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    headers: new Headers({ "content-type": "application/pdf", "content-disposition": 'attachment; filename="formulario.pdf"' }),
    blob: () => Promise.resolve(new Blob(["PDF"])),
  }));
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  const download = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.download).toBe("formulario.pdf");
  });
  render(<DownloadRow href="/test" icon="file" title="申告書" desc="PDF" tag="PDF" />);
  fireEvent.click(screen.getByRole("button", { name: /申告書/ }));
  await vi.waitFor(() => expect(download).toHaveBeenCalledOnce());
});

it("explica por qué no se pudo crear el paquete ZIP", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false,
    json: () => Promise.resolve({ detail: { code: "official_package_file_missing" } }),
  }));
  render(<DownloadRow href="/zip" icon="archive" title="Paquete ZIP" desc="Documentos" tag="ZIP" />);
  fireEvent.click(screen.getByRole("button", { name: /Paquete ZIP/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("No se ha generado el paquete");
});
