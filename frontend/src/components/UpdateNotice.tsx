import { useRegisterSW } from "virtual:pwa-register/react";

export function UpdateNotice() {
  const { needRefresh: [needRefresh, setNeedRefresh], updateServiceWorker } = useRegisterSW();
  if (!needRefresh) return null;
  return (
    <aside role="status" className="fixed bottom-4 right-4 z-50 m-4 max-w-sm rounded-lg border border-[var(--color-hairline)] bg-[var(--color-paper)] p-4 shadow-lg">
      <p className="font-bold">Hay una actualización disponible</p>
      <p className="mt-2 text-sm">Guarda primero los formularios abiertos. Actualizar recarga esta pestaña y puede afectar otras pestañas de la app.</p>
      <div className="mt-3 flex gap-3">
        <button type="button" className="rounded-lg bg-[var(--color-sumi)] px-3 py-2 text-white" onClick={() => void updateServiceWorker(true)}>Actualizar ahora</button>
        <button type="button" className="rounded-lg border border-[var(--color-hairline)] px-3 py-2" onClick={() => setNeedRefresh(false)}>Más tarde</button>
      </div>
    </aside>
  );
}
