/**
 * Binding de React para la cola de captura (`captureQueue.ts`).
 *
 * Expone el estado de la cola con `useSyncExternalStore` y engancha los eventos
 * `online`/`offline` del navegador: al recuperar la conexion, las fotos que
 * quedaron esperando se suben solas sin que el usuario toque nada.
 */

import { useCallback, useEffect, useSyncExternalStore } from "react";

import {
  getCaptureQueue,
  pendingCount,
  type CaptureItem,
  type CaptureQueue,
} from "./captureQueue";

/** Estado de la cola listo para la UI. */
export interface CaptureQueueState {
  queue: CaptureQueue;
  items: readonly CaptureItem[];
  pending: number;
  online: boolean;
}

function subscribeOnline(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

/**
 * Suscribe el componente a la cola de captura compartida.
 *
 * @param year 年度 destino de las capturas (para rescatar las de otra sesion).
 * @returns Estado de la cola y la instancia para encolar/reintentar.
 */
export function useCaptureQueue(year: number): CaptureQueueState {
  const queue = getCaptureQueue();
  const items = useSyncExternalStore(
    queue.subscribe,
    queue.getSnapshot,
    queue.getSnapshot,
  );
  const online = useSyncExternalStore(
    subscribeOnline,
    () => navigator.onLine !== false,
    () => true,
  );

  // Rescata las fotos que quedaron sin subir (app cerrada, bateria, tunel).
  useEffect(() => {
    void queue.restore(year);
  }, [queue, year]);

  // Al volver la conexion, reencolar y vaciar la cola sin intervencion.
  useEffect(() => {
    if (online) queue.resumeOffline();
  }, [online, queue]);

  return { queue, items, pending: pendingCount(items), online };
}

/** Atajo tipado para encolar una foto en la cola compartida. */
export function useEnqueueCapture(year: number): (blob: Blob, name: string) => void {
  const queue = getCaptureQueue();
  return useCallback(
    (blob: Blob, name: string) => {
      void queue.enqueue(blob, name, year);
    },
    [queue, year],
  );
}
