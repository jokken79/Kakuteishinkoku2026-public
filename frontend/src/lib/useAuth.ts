/**
 * Estado de sesión del frontend.
 *
 * `/auth/status` es público justamente para esto: la app necesita saber, antes
 * de pedir cualquier dato, si tiene que mostrar la pantalla de login. Cuando el
 * backend no tiene el login configurado, `enabled` viene en `false` y la app se
 * comporta exactamente como antes.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchAuthStatus, logout, type AuthStatus } from "./api";

const AUTH_KEY = ["auth", "status"] as const;

/** Traduce el `?auth_error=` del callback a un mensaje para el usuario. */
const AUTH_ERROR_MESSAGES: Record<string, string> = {
  not_allowed: "このアカウントはこのアプリを利用できません。",
  state_invalid: "ログインの有効期限が切れました。もう一度お試しください。",
  cancelled: "ログインがキャンセルされました。",
  failed: "Googleでの認証に失敗しました。もう一度お試しください。",
  no_code: "Googleから認可コードが届きませんでした。",
};

/**
 * Lee el motivo de rechazo que dejó el callback en la URL.
 *
 * @returns Mensaje en japonés listo para mostrar, o `null` si no hubo error.
 */
export function readAuthError(): string | null {
  if (typeof window === "undefined") return null;
  const code = new URLSearchParams(window.location.search).get("auth_error");
  if (!code) return null;
  return AUTH_ERROR_MESSAGES[code] ?? "ログインできませんでした。";
}

/** Saca el `?auth_error=` de la barra de direcciones sin recargar. */
export function clearAuthError(): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (!url.searchParams.has("auth_error")) return;
  url.searchParams.delete("auth_error");
  window.history.replaceState({}, "", url.pathname + url.search + url.hash);
}

/** Estado de sesión resuelto para la UI. */
export interface AuthState {
  /** `true` mientras todavía no se sabe si hay que pedir login. */
  loading: boolean;
  /** `true` si hay que mostrar la pantalla de acceso. */
  needsLogin: boolean;
  status: AuthStatus | undefined;
}

/**
 * Consulta el estado de sesión.
 *
 * @returns Estado listo para decidir entre login y app.
 */
export function useAuth(): AuthState {
  const query = useQuery({
    queryKey: AUTH_KEY,
    queryFn: ({ signal }) => fetchAuthStatus(signal),
    // La sesión puede vencer o revocarse del lado del servidor: se revalida al
    // volver a la pestaña en vez de confiar en una respuesta vieja.
    refetchOnWindowFocus: true,
    staleTime: 60_000,
    retry: false,
  });

  return {
    // Si `/auth/status` no responde, no se bloquea la app con una pantalla de
    // login que tampoco va a funcionar: se deja entrar y que fallen los datos
    // con su propio mensaje.
    loading: query.isLoading,
    needsLogin: query.data?.enabled === true && query.data.authenticated === false,
    status: query.data,
  };
}

/** Cierra la sesión y vuelve a la pantalla de acceso. */
export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => logout(),
    onSuccess: () => {
      // Toda la caché es del usuario que se acaba de ir.
      qc.clear();
      void qc.invalidateQueries({ queryKey: AUTH_KEY });
    },
  });
}
