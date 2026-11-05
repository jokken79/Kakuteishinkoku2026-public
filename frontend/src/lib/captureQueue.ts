/**
 * Cola de captura de recibos (連続撮影 + オフライン).
 *
 * Sacar la foto y esperar el OCR es lo que hace lento a cualquier app de gastos.
 * Aca la foto entra a una cola y se sube en segundo plano: la camara sigue
 * abierta y se pueden encadenar recibos sin esperar. Si no hay conexion (o el
 * backend local esta apagado), la foto queda guardada en IndexedDB y se sube
 * sola al volver la red — nada se pierde saliendo del comercio.
 *
 * El almacenamiento es inyectable (`CaptureStore`) para poder testear la logica
 * de la cola sin IndexedDB.
 */

import { ApiError, uploadReceipt, type ReceiptResponse } from "./api";

/** Estado de una captura dentro de la cola. */
export type CaptureStatus =
  | "queued"
  | "uploading"
  | "done"
  | "duplicate"
  | "offline"
  | "error";

/** Una foto encolada y su resultado de OCR (si ya subio). */
export interface CaptureItem {
  id: string;
  fileName: string;
  year: number;
  createdAt: number;
  status: CaptureStatus;
  attempts: number;
  /** Bytes de la foto; se sueltan cuando la subida termina bien. */
  blob: Blob | null;
  /** Miniatura (object URL) para la tira de resultados. */
  thumbUrl: string | null;
  error: string | null;
  /** Aviso persistente (ej. no se pudo cachear la foto), independiente del estado. */
  warning: string | null;
  result: ReceiptResponse | null;
  /** `true` cuando el usuario ya confirmo el 仕訳 de esta captura. */
  confirmed: boolean;
}

/** Fila persistida: como se guarda un item entre sesiones. */
export interface StoredCapture {
  id: string;
  fileName: string;
  year: number;
  createdAt: number;
  attempts: number;
  blob: Blob;
}

/** Almacenamiento de la cola (IndexedDB en el navegador, memoria en tests). */
export interface CaptureStore {
  all(): Promise<StoredCapture[]>;
  put(row: StoredCapture): Promise<void>;
  remove(id: string): Promise<void>;
}

const DB_NAME = "kakutei-capture-queue";
const DB_VERSION = 1;
const STORE_NAME = "captures";
/** Reintentos antes de dejar la captura en `error` para revision manual. */
const MAX_ATTEMPTS = 4;
/** Espera entre reintentos por fallo de red (ms). */
const RETRY_DELAYS_MS = [1_000, 4_000, 10_000];
/** Aviso cuando el almacen local no acepta la foto (cuota, modo privado...). */
const STORE_UNAVAILABLE_MESSAGE =
  "端末に保存できませんでした。このまま送信しますが、アプリを閉じると失われます。";

/** Almacenamiento en memoria (tests y navegadores sin IndexedDB). */
export function createMemoryStore(): CaptureStore {
  const rows = new Map<string, StoredCapture>();
  return {
    all: () => Promise.resolve([...rows.values()]),
    put: (row) => {
      rows.set(row.id, row);
      return Promise.resolve();
    },
    remove: (id) => {
      rows.delete(id);
      return Promise.resolve();
    },
  };
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) {
        request.result.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("indexeddb"));
  });
}

function promisify<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("indexeddb"));
  });
}

/** Almacenamiento persistente en IndexedDB (sobrevive cerrar la app). */
export function createIndexedDbStore(): CaptureStore {
  return {
    async all() {
      const db = await openDb();
      const tx = db.transaction(STORE_NAME, "readonly");
      const rows = await promisify(tx.objectStore(STORE_NAME).getAll());
      db.close();
      return rows as StoredCapture[];
    },
    async put(row) {
      const db = await openDb();
      const tx = db.transaction(STORE_NAME, "readwrite");
      await promisify(tx.objectStore(STORE_NAME).put(row));
      db.close();
    },
    async remove(id) {
      const db = await openDb();
      const tx = db.transaction(STORE_NAME, "readwrite");
      await promisify(tx.objectStore(STORE_NAME).delete(id));
      db.close();
    },
  };
}

/** Almacenamiento por defecto segun el entorno. */
export function defaultStore(): CaptureStore {
  if (typeof indexedDB === "undefined") return createMemoryStore();
  return createIndexedDbStore();
}

/** Opciones de la cola (todo inyectable para tests). */
export interface CaptureQueueOptions {
  store?: CaptureStore;
  upload?: (file: File, year: number) => Promise<ReceiptResponse>;
  isOnline?: () => boolean;
  wait?: (ms: number) => Promise<void>;
  makeId?: () => string;
  makeThumbUrl?: (blob: Blob) => string | null;
  revokeThumbUrl?: (url: string) => void;
}

function defaultId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `cap-${Date.now()}-${Math.round(Math.random() * 1e6)}`;
}

function defaultThumb(blob: Blob): string | null {
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    return null;
  }
  return URL.createObjectURL(blob);
}

/**
 * Cola serial de subida de recibos con persistencia y reintentos.
 *
 * Serial a proposito: en el celular, subir de a una foto mantiene la camara
 * fluida y no satura la conexion ni la cuota del OCR.
 */
export class CaptureQueue {
  private items: CaptureItem[] = [];
  private listeners = new Set<() => void>();
  private running: Promise<void> | null = null;
  private snapshot: readonly CaptureItem[] = [];
  private readonly store: CaptureStore;
  private readonly upload: (file: File, year: number) => Promise<ReceiptResponse>;
  private readonly isOnline: () => boolean;
  private readonly wait: (ms: number) => Promise<void>;
  private readonly makeId: () => string;
  private readonly makeThumbUrl: (blob: Blob) => string | null;
  private readonly revokeThumbUrl: (url: string) => void;

  constructor(options: CaptureQueueOptions = {}) {
    this.store = options.store ?? defaultStore();
    this.upload = options.upload ?? ((file, year) => uploadReceipt(file, year));
    this.isOnline =
      options.isOnline ??
      (() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
    this.wait =
      options.wait ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    this.makeId = options.makeId ?? defaultId;
    this.makeThumbUrl = options.makeThumbUrl ?? defaultThumb;
    this.revokeThumbUrl =
      options.revokeThumbUrl ??
      ((url) => {
        if (typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
          URL.revokeObjectURL(url);
        }
      });
    this.snapshot = [];
  }

  /** Estado actual de la cola (referencia estable entre cambios). */
  getSnapshot = (): readonly CaptureItem[] => this.snapshot;

  /** Suscribe un listener a los cambios de la cola. */
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /**
   * Recupera las capturas que quedaron sin subir de una sesion anterior.
   *
   * @returns Cantidad de capturas rescatadas.
   */
  async restore(year: number): Promise<number> {
    let rows: StoredCapture[];
    try {
      rows = await this.store.all();
    } catch {
      // Sin almacen local no hay nada que rescatar, pero la pantalla tiene que
      // abrir igual y poder seguir sacando fotos.
      return 0;
    }
    const known = new Set(this.items.map((item) => item.id));
    const restored = rows
      .filter((row) => !known.has(row.id))
      .map<CaptureItem>((row) => ({
        id: row.id,
        fileName: row.fileName,
        year: row.year || year,
        createdAt: row.createdAt,
        status: "queued",
        attempts: 0,
        blob: row.blob,
        thumbUrl: this.makeThumbUrl(row.blob),
        error: null,
        warning: null,
        result: null,
        confirmed: false,
      }));
    if (restored.length === 0) return 0;
    this.items = [...this.items, ...restored].sort(
      (a, b) => a.createdAt - b.createdAt,
    );
    this.emit();
    void this.flush();
    return restored.length;
  }

  /**
   * Encola una foto y dispara la subida en segundo plano.
   *
   * @param blob Imagen (o PDF) capturada.
   * @param fileName Nombre del archivo a enviar.
   * @param year 年度 destino.
   * @returns El item encolado.
   */
  async enqueue(blob: Blob, fileName: string, year: number): Promise<CaptureItem> {
    const item: CaptureItem = {
      id: this.makeId(),
      fileName,
      year,
      createdAt: Date.now(),
      status: "queued",
      attempts: 0,
      blob,
      thumbUrl: this.makeThumbUrl(blob),
      error: null,
      warning: null,
      result: null,
      confirmed: false,
    };
    this.items = [...this.items, item];
    this.emit();
    const persisted = await this.tryStore(() =>
      this.store.put({
        id: item.id,
        fileName: item.fileName,
        year: item.year,
        createdAt: item.createdAt,
        attempts: 0,
        blob,
      }),
    );
    if (!persisted) {
      // Cuota llena, modo privado o IndexedDB caido: la foto vive solo en
      // memoria. Se sube igual — perderla por no poder cachearla seria peor —
      // pero se avisa que no sobrevive cerrar la app.
      this.patch(item.id, { warning: STORE_UNAVAILABLE_MESSAGE });
    }
    void this.flush();
    return item;
  }

  /** Reintenta una captura que quedo en `error` u `offline`. */
  retry(id: string): void {
    const item = this.items.find((entry) => entry.id === id);
    if (!item || item.blob === null) return;
    this.patch(id, { status: "queued", attempts: 0, error: null });
    void this.flush();
  }

  /** Marca una captura como ya confirmada por el usuario. */
  markConfirmed(id: string): void {
    this.patch(id, { confirmed: true });
  }

  /**
   * Cambia el 勘定科目 propuesto de una captura ya leida (antes de confirmar).
   *
   * Solo toca el resultado en memoria: lo que persiste el 科目 es la
   * confirmacion, que lo manda junto con el resto de las correcciones.
   */
  setAccount(id: string, accountCode: string): void {
    const item = this.items.find((entry) => entry.id === id);
    if (!item?.result) return;
    this.patch(id, {
      result: {
        ...item.result,
        journal_suggestion: {
          ...item.result.journal_suggestion,
          account_code: accountCode,
        },
        transaction: { ...item.result.transaction, account_code: accountCode },
      },
    });
  }

  /** Quita una captura de la cola y libera su miniatura. */
  async remove(id: string): Promise<void> {
    const item = this.items.find((entry) => entry.id === id);
    if (item?.thumbUrl) this.revokeThumbUrl(item.thumbUrl);
    this.items = this.items.filter((entry) => entry.id !== id);
    this.emit();
    await this.tryStore(() => this.store.remove(id));
  }

  /** Vacia las capturas ya resueltas (subidas o duplicadas). */
  async clearFinished(): Promise<void> {
    const finished = this.items.filter(
      (item) => item.status === "done" || item.status === "duplicate",
    );
    for (const item of finished) {
      if (item.thumbUrl) this.revokeThumbUrl(item.thumbUrl);
      await this.tryStore(() => this.store.remove(item.id));
    }
    this.items = this.items.filter(
      (item) => item.status !== "done" && item.status !== "duplicate",
    );
    this.emit();
  }

  /**
   * Sube las capturas pendientes de a una, reintentando los fallos de red.
   *
   * Reentrante: si ya hay una corrida en curso devuelve esa misma promesa, asi
   * el llamador puede esperar a que la cola se vacie sin arrancar dos corridas.
   *
   * @returns Promesa que resuelve cuando no quedan capturas por subir.
   */
  flush(): Promise<void> {
    this.running ??= this.drain().finally(() => {
      this.running = null;
    });
    return this.running;
  }

  private async drain(): Promise<void> {
    for (;;) {
      const next = this.items.find((item) => item.status === "queued");
      if (!next || next.blob === null) break;
      if (!this.isOnline()) {
        this.patch(next.id, {
          status: "offline",
          error: "オフラインです。接続が戻ると自動で送信します。",
        });
        continue;
      }
      await this.uploadOne(next);
    }
  }

  /** Reencola las capturas que quedaron esperando conexion. */
  resumeOffline(): void {
    let changed = false;
    this.items = this.items.map((item) => {
      if (item.status !== "offline" || item.blob === null) return item;
      changed = true;
      return { ...item, status: "queued", error: null };
    });
    if (changed) {
      this.emit();
      void this.flush();
    }
  }

  private async uploadOne(item: CaptureItem): Promise<void> {
    const blob = item.blob;
    if (blob === null) return;
    this.patch(item.id, { status: "uploading", error: null });
    const file = new File([blob], item.fileName, {
      type: blob.type || "image/jpeg",
    });
    let result: ReceiptResponse;
    try {
      result = await this.upload(file, item.year);
    } catch (err) {
      await this.handleUploadError(item, err);
      return;
    }
    this.patch(item.id, {
      status: result.duplicate ? "duplicate" : "done",
      result,
      blob: null,
      error: null,
    });
    // El recibo ya esta en el servidor: si no se puede limpiar la copia local,
    // no es un fallo de subida (reencolarla la subiria dos veces).
    await this.tryStore(() => this.store.remove(item.id));
  }

  /**
   * Corre una operacion del almacen local sin dejar que su falla corte el flujo.
   *
   * @returns `true` si la operacion funciono, `false` si el almacen fallo.
   */
  private async tryStore(op: () => Promise<void>): Promise<boolean> {
    try {
      await op();
      return true;
    } catch {
      return false;
    }
  }

  private async handleUploadError(item: CaptureItem, err: unknown): Promise<void> {
    const apiError = err instanceof ApiError ? err : null;
    // Solo los fallos de red/servidor merecen reintento: un 4xx no se arregla
    // reenviando la misma foto.
    const retriable =
      apiError === null || apiError.status === 0 || apiError.status >= 500;
    const attempts = item.attempts + 1;
    const message =
      apiError?.message ?? "読み取りに失敗しました。もう一度お試しください。";

    if (retriable && !this.isOnline()) {
      this.patch(item.id, {
        status: "offline",
        attempts,
        error: "オフラインです。接続が戻ると自動で送信します。",
      });
      return;
    }
    if (retriable && attempts < MAX_ATTEMPTS) {
      this.patch(item.id, { status: "queued", attempts, error: message });
      const delay = RETRY_DELAYS_MS[Math.min(attempts - 1, RETRY_DELAYS_MS.length - 1)];
      await this.wait(delay);
      return;
    }
    this.patch(item.id, { status: "error", attempts, error: message });
  }

  private patch(id: string, patch: Partial<CaptureItem>): void {
    let changed = false;
    this.items = this.items.map((item) => {
      if (item.id !== id) return item;
      changed = true;
      return { ...item, ...patch };
    });
    if (changed) this.emit();
  }

  private emit(): void {
    this.snapshot = [...this.items];
    for (const listener of this.listeners) listener();
  }
}

let sharedQueue: CaptureQueue | null = null;

/** Cola compartida por la app (una sola por sesion). */
export function getCaptureQueue(): CaptureQueue {
  sharedQueue ??= new CaptureQueue();
  return sharedQueue;
}

/** Reemplaza la cola compartida (solo tests). */
export function setCaptureQueue(queue: CaptureQueue | null): void {
  sharedQueue = queue;
}

/** Cantidad de capturas todavia en vuelo (encoladas, subiendo u offline). */
export function pendingCount(items: readonly CaptureItem[]): number {
  return items.filter(
    (item) =>
      item.status === "queued" ||
      item.status === "uploading" ||
      item.status === "offline",
  ).length;
}
