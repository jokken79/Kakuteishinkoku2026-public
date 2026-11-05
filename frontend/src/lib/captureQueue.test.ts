/**
 * Tests de la cola de captura: subida en segundo plano, deduplicacion,
 * reintentos y modo offline (las fotos no se pierden sin conexion).
 */
import { describe, expect, it, vi } from "vitest";

import { ApiError, type ReceiptResponse } from "./api";
import {
  CaptureQueue,
  createMemoryStore,
  pendingCount,
  type CaptureStore,
} from "./captureQueue";

function fakeResult(overrides: Partial<ReceiptResponse> = {}): ReceiptResponse {
  return {
    transaction: {
      id: "tx-1",
      date: "2025-05-03",
      vendor: "セブンイレブン",
      total_amount: 868,
      registration_number: null,
      is_qualified_invoice: false,
      confidence: 0.9,
      status: "pending",
      tax_lines: [],
      evidence_id: null,
      account_code: "502",
      field_confidences: null,
    },
    journal_suggestion: {
      date: "2025-05-03",
      description: "セブンイレブン",
      lines: [],
      account_code: "502",
      account_confidence: 0.8,
    },
    confidence: 0.9,
    confidence_level: "high",
    provider_used: "fake",
    validation_errors: [],
    duplicate: false,
    duplicate_of: null,
    account_source: "rule",
    ...overrides,
  };
}

interface QueueHarness {
  queue: CaptureQueue;
  store: CaptureStore;
  online: { value: boolean };
}

function makeQueue(
  upload: (file: File, year: number) => Promise<ReceiptResponse>,
): QueueHarness {
  const store = createMemoryStore();
  const online = { value: true };
  let seq = 0;
  const queue = new CaptureQueue({
    store,
    upload,
    isOnline: () => online.value,
    wait: () => Promise.resolve(),
    makeId: () => `cap-${++seq}`,
    makeThumbUrl: () => null,
    revokeThumbUrl: () => undefined,
  });
  return { queue, store, online };
}

function photo(): Blob {
  return new Blob(["image-bytes"], { type: "image/jpeg" });
}

describe("CaptureQueue", () => {
  it("sube la foto en segundo plano y deja el 仕訳 propuesto listo", async () => {
    const upload = vi.fn().mockResolvedValue(fakeResult());
    const { queue, store } = makeQueue(upload);

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.flush();

    const [item] = queue.getSnapshot();
    expect(item.status).toBe("done");
    expect(item.result?.transaction.vendor).toBe("セブンイレブン");
    // La foto ya subida no ocupa mas espacio en el celular.
    expect(item.blob).toBeNull();
    expect(await store.all()).toEqual([]);
  });

  it("encadena varias capturas sin esperar a la anterior", async () => {
    const upload = vi.fn().mockResolvedValue(fakeResult());
    const { queue } = makeQueue(upload);

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.enqueue(photo(), "r2.jpg", 2025);
    await queue.enqueue(photo(), "r3.jpg", 2025);
    await queue.flush();

    expect(upload).toHaveBeenCalledTimes(3);
    expect(queue.getSnapshot().map((item) => item.status)).toEqual([
      "done",
      "done",
      "done",
    ]);
    expect(pendingCount(queue.getSnapshot())).toBe(0);
  });

  it("marca como duplicada la foto que el backend ya tenia archivada", async () => {
    const upload = vi.fn().mockResolvedValue(fakeResult({ duplicate: true }));
    const { queue } = makeQueue(upload);

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.flush();

    expect(queue.getSnapshot()[0].status).toBe("duplicate");
  });

  it("guarda la foto sin conexion y la envia sola al volver la red", async () => {
    const upload = vi.fn().mockResolvedValue(fakeResult());
    const { queue, store, online } = makeQueue(upload);
    online.value = false;

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.flush();

    expect(upload).not.toHaveBeenCalled();
    expect(queue.getSnapshot()[0].status).toBe("offline");
    // La foto sigue en el almacen local: no se pierde nada.
    expect(await store.all()).toHaveLength(1);

    online.value = true;
    queue.resumeOffline();
    await queue.flush();

    expect(upload).toHaveBeenCalledTimes(1);
    expect(queue.getSnapshot()[0].status).toBe("done");
  });

  it("reintenta los fallos de red y termina subiendo", async () => {
    const upload = vi
      .fn()
      .mockRejectedValueOnce(new ApiError("バックエンドに接続できません。", 0, "network"))
      .mockResolvedValue(fakeResult());
    const { queue } = makeQueue(upload);

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.flush();

    expect(upload).toHaveBeenCalledTimes(2);
    expect(queue.getSnapshot()[0].status).toBe("done");
  });

  it("no reintenta un rechazo del servidor (4xx) y deja el error visible", async () => {
    const upload = vi
      .fn()
      .mockRejectedValue(new ApiError("入力内容に問題があります。", 400, "empty_file"));
    const { queue } = makeQueue(upload);

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.flush();

    expect(upload).toHaveBeenCalledTimes(1);
    const [item] = queue.getSnapshot();
    expect(item.status).toBe("error");
    expect(item.error).toBe("入力内容に問題があります。");
  });

  it("deja reintentar a mano una captura fallida", async () => {
    const upload = vi
      .fn()
      .mockRejectedValueOnce(new ApiError("入力内容に問題があります。", 400))
      .mockResolvedValue(fakeResult());
    const { queue } = makeQueue(upload);

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.flush();
    expect(queue.getSnapshot()[0].status).toBe("error");

    queue.retry(queue.getSnapshot()[0].id);
    await queue.flush();

    expect(queue.getSnapshot()[0].status).toBe("done");
  });

  it("rescata las fotos que quedaron sin subir de una sesion anterior", async () => {
    const store = createMemoryStore();
    await store.put({
      id: "cap-old",
      fileName: "r-old.jpg",
      year: 2025,
      createdAt: 1,
      attempts: 0,
      blob: photo(),
    });
    const upload = vi.fn().mockResolvedValue(fakeResult());
    const queue = new CaptureQueue({
      store,
      upload,
      isOnline: () => true,
      wait: () => Promise.resolve(),
      makeThumbUrl: () => null,
      revokeThumbUrl: () => undefined,
    });

    expect(await queue.restore(2025)).toBe(1);
    await queue.flush();

    expect(upload).toHaveBeenCalledTimes(1);
    expect(queue.getSnapshot()[0].status).toBe("done");
  });

  it("cambia el 科目 propuesto antes de confirmar", async () => {
    const upload = vi.fn().mockResolvedValue(fakeResult());
    const { queue } = makeQueue(upload);

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.flush();

    const id = queue.getSnapshot()[0].id;
    queue.setAccount(id, "504");

    const [item] = queue.getSnapshot();
    expect(item.result?.journal_suggestion.account_code).toBe("504");
    expect(item.result?.transaction.account_code).toBe("504");
  });

  it("limpia solo las capturas ya resueltas", async () => {
    const upload = vi
      .fn()
      .mockResolvedValueOnce(fakeResult())
      .mockRejectedValueOnce(new ApiError("入力内容に問題があります。", 400));
    const { queue } = makeQueue(upload);

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.enqueue(photo(), "r2.jpg", 2025);
    await queue.flush();

    await queue.clearFinished();

    const remaining = queue.getSnapshot();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].status).toBe("error");
  });
  it("sube igual aunque el almacen local rechace la foto, avisando al usuario", async () => {
    const upload = vi.fn().mockResolvedValue(fakeResult());
    const broken: CaptureStore = {
      all: () => Promise.resolve([]),
      put: () => Promise.reject(new Error("QuotaExceededError")),
      remove: () => Promise.resolve(),
    };
    const queue = new CaptureQueue({
      store: broken,
      upload,
      isOnline: () => true,
      wait: () => Promise.resolve(),
      makeThumbUrl: () => null,
      revokeThumbUrl: () => undefined,
    });

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.flush();

    // Perder el recibo por no poder cachearlo seria peor que subirlo sin cache.
    expect(upload).toHaveBeenCalledTimes(1);
    const [item] = queue.getSnapshot();
    expect(item.status).toBe("done");
    // El aviso sobrevive al ciclo de subida: el usuario tiene que enterarse de
    // que esa foto no estaba respaldada en el celular.
    expect(item.warning).toContain("端末に保存できませんでした");
  });

  it("no reencola cuando falla solo el borrado local tras subir", async () => {
    const upload = vi.fn().mockResolvedValue(fakeResult());
    const store: CaptureStore = {
      all: () => Promise.resolve([]),
      put: () => Promise.resolve(),
      remove: () => Promise.reject(new Error("indexeddb")),
    };
    const queue = new CaptureQueue({
      store,
      upload,
      isOnline: () => true,
      wait: () => Promise.resolve(),
      makeThumbUrl: () => null,
      revokeThumbUrl: () => undefined,
    });

    await queue.enqueue(photo(), "r1.jpg", 2025);
    await queue.flush();

    // Reintentar por un borrado fallido subiria el mismo recibo dos veces.
    expect(upload).toHaveBeenCalledTimes(1);
    expect(queue.getSnapshot()[0].status).toBe("done");
  });

  it("abre igual cuando el almacen local no se puede leer", async () => {
    const broken: CaptureStore = {
      all: () => Promise.reject(new Error("indexeddb")),
      put: () => Promise.resolve(),
      remove: () => Promise.resolve(),
    };
    const queue = new CaptureQueue({
      store: broken,
      upload: vi.fn().mockResolvedValue(fakeResult()),
      isOnline: () => true,
      wait: () => Promise.resolve(),
      makeThumbUrl: () => null,
      revokeThumbUrl: () => undefined,
    });

    await expect(queue.restore(2025)).resolves.toBe(0);
  });
});
