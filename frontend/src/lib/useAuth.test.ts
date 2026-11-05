/**
 * Tests de la lógica de sesión del frontend.
 *
 * Lo que se protege: que el motivo de rechazo del callback llegue traducido al
 * usuario (y no como un código crudo), y que no quede pegado en la URL después
 * de mostrarlo.
 */
import { afterEach, describe, expect, it } from "vitest";

import { clearAuthError, readAuthError } from "./useAuth";

function setUrl(search: string): void {
  window.history.replaceState({}, "", `/${search}`);
}

afterEach(() => {
  setUrl("");
});

describe("readAuthError", () => {
  it("no reporta nada cuando el login salió bien", () => {
    setUrl("");
    expect(readAuthError()).toBeNull();
  });

  it("traduce el rechazo por allowlist, que es el caso que más confunde", () => {
    setUrl("?auth_error=not_allowed");
    expect(readAuthError()).toBe("このアカウントはこのアプリを利用できません。");
  });

  it("traduce el resto de los motivos del callback", () => {
    setUrl("?auth_error=state_invalid");
    expect(readAuthError()).toContain("有効期限");

    setUrl("?auth_error=cancelled");
    expect(readAuthError()).toContain("キャンセル");

    setUrl("?auth_error=failed");
    expect(readAuthError()).toContain("認証に失敗");
  });

  it("da un mensaje genérico ante un código desconocido, nunca el código crudo", () => {
    setUrl("?auth_error=algo_nuevo");
    const message = readAuthError();
    expect(message).toBe("ログインできませんでした。");
    expect(message).not.toContain("algo_nuevo");
  });
});

describe("clearAuthError", () => {
  it("saca el parámetro para que el error no reaparezca al recargar", () => {
    setUrl("?auth_error=not_allowed");
    clearAuthError();
    expect(window.location.search).toBe("");
    expect(readAuthError()).toBeNull();
  });

  it("conserva los demás parámetros de la URL", () => {
    setUrl("?year=2025&auth_error=cancelled");
    clearAuthError();
    expect(window.location.search).toBe("?year=2025");
  });

  it("no rompe si no hay error que limpiar", () => {
    setUrl("?year=2025");
    clearAuthError();
    expect(window.location.search).toBe("?year=2025");
  });
});
