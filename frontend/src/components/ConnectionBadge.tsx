import { useEffect, useState } from "react";
import { fetchHealth, type HealthStatus } from "../lib/api";

type ConnectionState = "checking" | "online" | "offline";

/**
 * Badge sereno del estado de conexion con el backend. Consulta `/health` al
 * montar y cada 15s. Punto de color + texto japones, sin estridencia.
 */
export function ConnectionBadge() {
  const [state, setState] = useState<ConnectionState>("checking");
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    const check = async (): Promise<void> => {
      try {
        const result = await fetchHealth(controller.signal);
        if (!active) return;
        setHealth(result);
        setState("online");
      } catch {
        if (!active) return;
        setHealth(null);
        setState("offline");
      }
    };

    void check();
    const interval = window.setInterval(() => void check(), 15_000);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(interval);
    };
  }, []);

  const config: Record<ConnectionState, { dot: string; label: string }> = {
    checking: { dot: "bg-[var(--color-kohaku)]", label: "接続確認中" },
    online: {
      dot: "bg-[var(--color-seiji)]",
      label: health ? "接続済み" : "接続済み",
    },
    offline: { dot: "bg-[var(--color-kohaku)]", label: "未接続" },
  };

  const { dot, label } = config[state];

  return (
    <div className="flex items-center gap-2 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-1.5 text-xs font-medium text-[var(--color-sumi-soft)]">
      <span className={`inline-block h-2 w-2 rounded-full ${dot}`} aria-hidden />
      <span>{label}</span>
    </div>
  );
}
