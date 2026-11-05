import { describe, expect, it } from "vitest";
import {
  accountCategory,
  accountName,
  confidenceLevel,
  confidencePct,
  daysUntil,
  filingDeadlineForYear,
  formatAmount,
  formatDate,
  formatYen,
  reviewHint,
  toReiwa,
} from "./format";

describe("formatYen", () => {
  it("formatea enteros con separador de millares", () => {
    expect(formatYen(1234567)).toBe("¥1,234,567");
  });
  it("usa el signo menos tipográfico para negativos", () => {
    expect(formatYen(-5000)).toBe("−¥5,000");
  });
  it("devuelve ¥— para null/undefined", () => {
    expect(formatYen(null)).toBe("¥—");
    expect(formatYen(undefined)).toBe("¥—");
  });
  it("trata el 0 como valor (no como vacío)", () => {
    expect(formatYen(0)).toBe("¥0");
  });
});

describe("formatAmount", () => {
  it("formatea sin símbolo ¥", () => {
    expect(formatAmount(98765)).toBe("98,765");
  });
  it("usa valor absoluto", () => {
    expect(formatAmount(-42)).toBe("42");
  });
  it("devuelve — para nulos", () => {
    expect(formatAmount(undefined)).toBe("—");
  });
});

describe("toReiwa", () => {
  it("convierte 西暦 a 令和 (令和 = 2018-base)", () => {
    expect(toReiwa(2025)).toBe("令和7年");
    expect(toReiwa(2019)).toBe("令和1年");
  });
});

describe("formatDate", () => {
  it("reemplaza guiones por barras", () => {
    expect(formatDate("2025-06-14")).toBe("2025/06/14");
  });
  it("devuelve — para vacío", () => {
    expect(formatDate(null)).toBe("—");
  });
});

describe("accountName / accountCategory", () => {
  it("mapea código de 勘定科目 a nombre", () => {
    expect(accountName("501")).toBe("旅費交通費");
  });
  it("devuelve el código si no está mapeado", () => {
    expect(accountName("999999")).toBe("999999");
  });
  it("devuelve 未分類 para código nulo", () => {
    expect(accountName(null)).toBe("未分類");
  });
  it("clasifica la categoría visual conocida y cae a generic", () => {
    expect(accountCategory("501")).toBe("travel");
    expect(accountCategory("505")).toBe("comm");
    expect(accountCategory("000")).toBe("generic");
  });
});

describe("confidence helpers", () => {
  it("umbral 0.75 separa high/low (espejo del backend)", () => {
    expect(confidenceLevel(0.75)).toBe("high");
    expect(confidenceLevel(0.7499)).toBe("low");
    expect(confidenceLevel(null)).toBe("low");
  });
  it("convierte score a porcentaje entero", () => {
    expect(confidencePct(0.836)).toBe(84);
    expect(confidencePct(null)).toBe(0);
  });
});

describe("reviewHint", () => {
  it("no avisa cuando la confianza global es alta", () => {
    expect(reviewHint(null, 0.9)).toBeNull();
  });
  it("elige el campo más débil bajo el umbral", () => {
    expect(reviewHint({ total: 0.9, date: 0.4 }, 0.5)).toBe("日付が不明瞭");
  });
  it("ignora campos con confianza <= 0 y cae a genérico", () => {
    expect(reviewHint({ registration_number: 0 }, 0.5)).toBe("内容を確認してください");
  });
});

describe("daysUntil / filingDeadlineForYear", () => {
  it("ajusta el plazo ordinario cuando el 15 cae en domingo", () => {
    const d = filingDeadlineForYear(2025);
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(2); // marzo (0-based)
    expect(d.getDate()).toBe(16);
  });
  it("mantiene el 15 de marzo cuando es lunes", () => {
    expect(filingDeadlineForYear(2026).getDate()).toBe(15);
  });
  it("ajusta el plazo ordinario cuando el 15 cae en sábado", () => {
    expect(filingDeadlineForYear(2024).getDate()).toBe(17);
  });
  it("daysUntil de hoy es 0", () => {
    expect(daysUntil(new Date())).toBe(0);
  });
  it("daysUntil de mañana es 1", () => {
    const t = new Date();
    t.setDate(t.getDate() + 1);
    expect(daysUntil(t)).toBe(1);
  });
});
