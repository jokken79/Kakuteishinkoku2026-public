"""Punto de entrada de la aplicacion FastAPI.

Configura CORS, logging y monta los routers de la API bajo el prefijo
`/api/v1`. La logica de negocio (motor contable, calculadora fiscal, OCR) vive
en `app/domain` y `app/services`; este modulo es solo el andamiaje del servicio.

Si existe el build de la PWA (`frontend/dist`), tambien la sirve en `/`: un solo
proceso y un solo origen, que es lo que hace que la app abra igual desde el
celular sin configurar URLs ni CORS (ver `docs/acceso-remoto.md`).

Cuando el login con Google esta configurado, un middleware exige sesion en TODA
la API salvo `/health` y `/auth/*`. Es fail-closed a proposito: un router nuevo
queda protegido sin que nadie se acuerde de protegerlo.
"""

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from app.api import (
    auth,
    business_profile,
    consumption,
    deductions,
    dependents,
    filing,
    fiscal_years,
    health,
    household,
    import_csv,
    import_koujo_xml,
    income,
    mixed_expenses,
    onboarding,
    past_filings,
    receipts,
    recommendations,
    remittances,
    sales_documents,
    tax,
    xtx,
    year_end,
)
from app.core.config import Settings, get_settings
from app.services.auth import SESSION_COOKIE, is_auth_configured, read_session
from app.services.forms.drafting import ClosedYearWithoutDraftError, UnidentifiedJournalEntriesError

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Crea y configura la instancia de FastAPI.

    Returns:
        Aplicacion FastAPI lista para servir.
    """
    settings = get_settings()
    app = FastAPI(
        title="確定申告 2026 API",
        version=settings.app_version,
        description="API del backend para la app de declaracion de impuestos JP.",
    )

    @app.exception_handler(UnidentifiedJournalEntriesError)
    async def unidentified_journal_entries(
        _request: Request, _exc: UnidentifiedJournalEntriesError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": {
            "code": "journal_origin_unknown",
            "message": (
                "Hay asientos antiguos sin origen identificado. El cálculo se detuvo sin "
                "borrarlos. Haz una copia de seguridad y revisa su procedencia antes de continuar."
            ),
            "details": {},
        }})

    @app.exception_handler(ClosedYearWithoutDraftError)
    async def closed_year_without_draft(
        _request: Request, _exc: ClosedYearWithoutDraftError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": {
            "code": "closed_year_without_draft",
            "message": (
                "Este ejercicio está cerrado y no tiene un borrador previo. "
                "No se han modificado sus datos."
            ),
            "details": {},
        }})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(tax.router, prefix=settings.api_prefix)
    app.include_router(receipts.router, prefix=settings.api_prefix)
    app.include_router(remittances.router, prefix=settings.api_prefix)
    app.include_router(import_csv.router, prefix=settings.api_prefix)
    app.include_router(deductions.router, prefix=settings.api_prefix)
    app.include_router(import_koujo_xml.router, prefix=settings.api_prefix)
    app.include_router(dependents.router, prefix=settings.api_prefix)
    app.include_router(income.router, prefix=settings.api_prefix)
    app.include_router(mixed_expenses.router, prefix=settings.api_prefix)
    app.include_router(filing.router, prefix=settings.api_prefix)
    app.include_router(xtx.router, prefix=settings.api_prefix)
    app.include_router(consumption.router, prefix=settings.api_prefix)
    app.include_router(onboarding.router, prefix=settings.api_prefix)
    app.include_router(past_filings.router, prefix=settings.api_prefix)
    app.include_router(recommendations.router, prefix=settings.api_prefix)
    app.include_router(household.router, prefix=settings.api_prefix)
    app.include_router(fiscal_years.router, prefix=settings.api_prefix)
    app.include_router(business_profile.router, prefix=settings.api_prefix)
    app.include_router(sales_documents.router, prefix=settings.api_prefix)
    app.include_router(year_end.router, prefix=settings.api_prefix)

    _install_auth_guard(app, settings)
    _mount_frontend(app, settings)

    logger.info("Aplicacion '%s' v%s inicializada", settings.app_name, settings.app_version)
    return app


def requires_auth(path: str, api_prefix: str) -> bool:
    """Indica si una ruta necesita sesion cuando el login esta activo.

    Protege TODA la API salvo dos excepciones necesarias: `/health` (lo consulta
    el badge de conexion antes de haber entrado) y `/auth/*` (es como se entra).
    Tambien cubre la documentacion generada, que describe la API entera.

    La logica es "todo protegido salvo lista corta" y no al reves: agregar un
    router nuevo no puede dejar un agujero por olvido.

    Args:
        path: Path del pedido.
        api_prefix: Prefijo de la API (ej. ``/api/v1``).

    Returns:
        ``True`` si hay que exigir sesion.
    """
    if path in ("/docs", "/redoc", "/openapi.json"):
        return True
    if not path.startswith(api_prefix):
        # La PWA estatica se sirve igual: sin sesion muestra la pantalla de
        # login, que necesita cargar para poder ofrecer el boton de Google.
        return False
    rest = path[len(api_prefix) :]
    if rest == "/health" or rest.startswith("/auth/"):
        return False
    return True


def _install_auth_guard(app: FastAPI, settings: Settings) -> None:
    """Instala el middleware que exige sesion cuando el login esta configurado.

    Si el login no esta configurado, el middleware deja pasar todo: la app sigue
    funcionando como siempre en local o por tailnet privada.

    Args:
        app: Aplicacion FastAPI.
        settings: Settings de la aplicacion.
    """
    if settings.auth_enabled and not is_auth_configured(settings):
        raise RuntimeError("AUTH_ENABLED requiere credenciales y una lista de correos autorizados")
    if not settings.auth_enabled:
        logger.info("Login con Google apagado: la API responde sin autenticacion.")
        return

    logger.info(
        "Login con Google activo (%d cuenta(s) habilitada(s)).",
        len(settings.auth_allowed_emails),
    )

    @app.middleware("http")
    async def _auth_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Corta los pedidos sin sesion valida a las rutas protegidas.

        Args:
            request: Pedido entrante.
            call_next: Siguiente handler de la cadena.

        Returns:
            La respuesta del handler, o un 401 con el codigo `auth_required`.
        """
        current = get_settings()
        if requires_auth(request.url.path, current.api_prefix):
            token = request.cookies.get(SESSION_COOKIE)
            if not token or read_session(token, settings=current) is None:
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": {
                            "code": "auth_required",
                            "message": "ログインが必要です。",
                            "details": {},
                        }
                    },
                )
        return await call_next(request)


def resolve_frontend_dist(settings: Settings) -> Path | None:
    """Resuelve la carpeta del build de la PWA a servir, si la hay.

    Usa `frontend_dist` de settings; si no esta seteada, autodetecta
    `frontend/dist` en la raiz del repo. Devuelve ``None`` si no hay build
    valido (falta la carpeta o su `index.html`), que es el caso normal en
    desarrollo, donde el frontend lo sirve Vite en :5200.

    Args:
        settings: Settings de la aplicacion.

    Returns:
        Ruta a la carpeta del build, o ``None`` si no hay build servible.
    """
    if settings.frontend_dist:
        candidate = Path(settings.frontend_dist)
    else:
        # app/main.py -> app -> backend -> raiz del repo
        candidate = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if not candidate.is_dir() or not (candidate / "index.html").is_file():
        return None
    return candidate


class FrontendStaticFiles(StaticFiles):
    """Revalida el HTML y el service worker al consultar una versión nueva."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if path in ("", ".", "index.html", "sw.js"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Monta la PWA compilada en `/`, despues de las rutas de la API.

    El orden importa: Starlette resuelve las rutas en orden de registro, asi que
    los routers de `/api/v1` (ya incluidos) ganan sobre este mount, que si no se
    quedaria con todo. La app no usa rutas de URL (la navegacion es estado en
    Zustand), por eso alcanza con `html=True` para servir `index.html` en `/`.

    Args:
        app: Aplicacion FastAPI con los routers ya montados.
        settings: Settings de la aplicacion.
    """
    dist = resolve_frontend_dist(settings)
    if dist is None:
        logger.info("Sin build de PWA: el frontend lo sirve Vite (dev).")
        return
    app.mount("/", FrontendStaticFiles(directory=dist, html=True), name="frontend")
    logger.info("PWA servida desde %s", dist)


app = create_app()
