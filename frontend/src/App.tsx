import { AnimatePresence } from "framer-motion";
import { Suspense, useEffect, useState } from "react";
import { AppShell } from "./components/Layout/AppShell";
import { ScreenErrorBoundary } from "./components/ScreenErrorBoundary";
import { UpdateNotice } from "./components/UpdateNotice";
import { ScreenLoading } from "./components/ui";
import { NAV_SECTIONS } from "./lib/navigation";
import {
  getLazyScreen,
  LazyOnboardingScreen,
  preloadOnboarding,
} from "./lib/screenRegistry";
import { useUiStore } from "./lib/store";
import { useOnboardingStatus } from "./lib/hooks";
import { clearAuthError, readAuthError, useAuth } from "./lib/useAuth";
import { LoginScreen } from "./screens/LoginScreen";
import { PlaceholderScreen } from "./screens/PlaceholderScreen";

/**
 * Raiz de la app de 確定申告.
 *
 * Orden de decision:
 *
 * 1. Si el backend tiene login con Google activo y esta sesion no esta
 *    autenticada, se muestra la pantalla de acceso y nada mas: los datos
 *    fiscales no se piden siquiera. Si el login esta apagado (uso local o por
 *    tailnet privada), este paso no existe.
 * 2. Si el usuario es nuevo (`onboarded=false`), el ONBOARDING guiado.
 * 3. Si no, el shell normal: header + navegacion + la pantalla activa (Zustand).
 */
function App() {
  const activeSection = useUiStore((s) => s.activeSection);
  const section =
    NAV_SECTIONS.find((s) => s.id === activeSection) ?? NAV_SECTIONS[0];

  const auth = useAuth();
  // El motivo de rechazo viaja en la URL una sola vez: se lee al montar y se
  // limpia, para que no reaparezca al recargar.
  const [authError] = useState(readAuthError);
  useEffect(() => {
    if (authError) clearAuthError();
  }, [authError]);

  const onboarding = useOnboardingStatus();
  // Mostramos el onboarding solo cuando SABEMOS que no esta onboardeado. Mientras
  // carga (o si el status falla) caemos al shell normal para no bloquear la app.
  const showOnboarding = onboarding.data?.onboarded === false;
  const Screen = getLazyScreen(section.id);

  useEffect(() => {
    if (showOnboarding) preloadOnboarding();
  }, [showOnboarding]);

  if (auth.loading) {
    return <ScreenLoading label="読み込み中です。" />;
  }

  if (auth.needsLogin) {
    return <LoginScreen error={authError} />;
  }

  return (
    <>
      <AppShell>
        <ScreenErrorBoundary key={section.id}>
          <Suspense fallback={<ScreenLoading label={`${section.label}を読み込み中です。`} />}>
            {Screen ? <Screen /> : <PlaceholderScreen section={section} />}
          </Suspense>
        </ScreenErrorBoundary>
      </AppShell>
      <UpdateNotice />
      <AnimatePresence>
        {showOnboarding && (
          <ScreenErrorBoundary>
            <Suspense fallback={null}>
              <LazyOnboardingScreen />
            </Suspense>
          </ScreenErrorBoundary>
        )}
      </AnimatePresence>
    </>
  );
}

export default App;
