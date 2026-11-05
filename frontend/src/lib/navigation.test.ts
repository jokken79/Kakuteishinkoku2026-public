import { describe, expect, it } from "vitest";
import { MOBILE_PRIMARY_IDS, NAV_SECTIONS } from "./navigation";

describe("NAV_SECTIONS", () => {
  it("tiene ids únicos", () => {
    const ids = NAV_SECTIONS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
  it("toda sección tiene id, label y grupo", () => {
    for (const s of NAV_SECTIONS) {
      expect(s.id).toBeTruthy();
      expect(s.label).toBeTruthy();
      expect(s.group).toBeTruthy();
    }
  });
});

describe("navegación móvil", () => {
  it("los ids primarios del móvil existen en NAV_SECTIONS", () => {
    const all = new Set(NAV_SECTIONS.map((s) => s.id));
    for (const id of MOBILE_PRIMARY_IDS) expect(all.has(id)).toBe(true);
  });
  it("la barra inferior tiene 5 ids primarios únicos", () => {
    expect(MOBILE_PRIMARY_IDS).toHaveLength(5);
    expect(new Set(MOBILE_PRIMARY_IDS).size).toBe(5);
  });
});
