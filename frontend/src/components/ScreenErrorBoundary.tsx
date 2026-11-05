import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { failed: boolean };

/** Mantiene la navegación disponible si falla la carga de una pantalla. */
export class ScreenErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("No se pudo abrir la pantalla", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section role="alert" className="m-4 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-paper)] p-5">
        <h2 className="text-lg font-bold">No se pudo abrir esta pantalla</h2>
        <p className="mt-2">Puede haber una actualización pendiente o un problema de conexión. Puedes abrir otra sección o recargar la aplicación.</p>
        <p className="mt-2 text-sm">Al recargar se perderán los cambios que aún no hayas guardado en cualquier formulario de esta pestaña.</p>
        <button type="button" className="mt-4 rounded-lg bg-[var(--color-sumi)] px-4 py-2 text-white" onClick={() => window.location.reload()}>Recargar aplicación</button>
      </section>
    );
  }
}
