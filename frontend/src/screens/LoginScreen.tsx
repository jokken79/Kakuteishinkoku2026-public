/**
 * Pantalla de acceso. Solo aparece cuando el backend tiene el login con Google
 * activo y esta sesion no esta autenticada.
 *
 * No hay formulario ni contraseña a propósito: la identidad la verifica Google
 * y la autorización la decide la allowlist del backend. Acá solo hay un botón.
 */
import { motion } from "framer-motion";
import { LOGIN_URL } from "../lib/api";
import { Card } from "../components/ui";
import { Icon } from "../components/Icon";

interface LoginScreenProps {
  /** Mensaje de error a mostrar (ej. cuenta fuera de la allowlist). */
  error?: string | null;
}

export function LoginScreen({ error = null }: LoginScreenProps) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-[var(--color-paper)] px-4 py-10">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-sm"
      >
        <Card className="p-7 text-center">
          <div className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-full bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
            <Icon name="shield" className="h-6 w-6" />
          </div>
          <h1 className="text-lg font-bold text-[var(--color-sumi)]">確定申告 2026</h1>
          <p className="mt-2 text-sm leading-relaxed text-[var(--color-sumi-soft)]">
            マイナンバーや帳簿を扱うため、ログインが必要です。
          </p>

          {error && (
            <div
              role="alert"
              className="mt-5 rounded-[var(--radius-card)] border border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] p-3.5 text-left"
            >
              <p className="text-sm text-[var(--color-sumi)]">{error}</p>
            </div>
          )}

          <a
            href={LOGIN_URL}
            className="mt-6 flex w-full items-center justify-center gap-2.5 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-3 text-sm font-semibold text-white transition-transform active:translate-y-px"
          >
            <GoogleGlyph />
            Googleでログイン
          </a>

          <p className="mt-5 text-xs leading-relaxed text-[var(--color-sumi-soft)]">
            許可されたアカウントのみ利用できます。
          </p>
        </Card>
      </motion.div>
    </div>
  );
}

/** Logotipo de Google (SVG inline: no se cargan recursos externos). */
function GoogleGlyph() {
  return (
    <svg viewBox="0 0 18 18" className="h-4 w-4" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.35 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.96 10.71a5.41 5.41 0 0 1 0-3.42V4.96H.96a9 9 0 0 0 0 8.08l3-2.33z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.96l3 2.33C4.67 5.16 6.65 3.58 9 3.58z"
      />
    </svg>
  );
}
