"""Router de login con Google.

Endpoints (bajo `/api/v1`):

- ``GET  /auth/status``   — si el login esta activo y quien esta adentro.
- ``GET  /auth/login``    — redirige a Google para elegir cuenta.
- ``GET  /auth/callback`` — vuelta de Google: canjea el codigo y abre la sesion.
- ``POST /auth/logout``   — cierra la sesion.

`/auth/status` es publico a proposito: es lo que el frontend consulta para saber
si tiene que mostrar la pantalla de login. Nunca revela la allowlist ni datos
del usuario si no hay sesion valida.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.services.auth import (
    SESSION_COOKIE,
    STATE_COOKIE,
    STATE_MAX_AGE,
    AuthError,
    build_authorization_url,
    exchange_code,
    is_auth_configured,
    is_email_allowed,
    issue_session,
    issue_state,
    read_session,
    read_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"], prefix="/auth")


class AuthStatus(BaseModel):
    """Estado del login para el frontend.

    Args:
        enabled: ``True`` si el login con Google esta activo y configurado.
        authenticated: ``True`` si este pedido trae una sesion valida.
        email: Direccion autenticada, o ``None``.
    """

    enabled: bool
    authenticated: bool
    email: str | None = None


def _redirect_uri(request: Request) -> str:
    """Arma el `redirect_uri` a partir del host por el que entro el pedido.

    Derivarlo del pedido (y no de una constante) es lo que permite que la misma
    instancia funcione en `localhost` y en la URL `.ts.net` de Tailscale sin
    reconfigurar nada. Ambas tienen que estar registradas en Google.

    Args:
        request: Pedido entrante.

    Returns:
        URL absoluta del callback.
    """
    return str(request.url_for("auth_callback"))


def _is_secure(request: Request) -> bool:
    """Indica si el pedido llego por HTTPS (para marcar la cookie `Secure`).

    Args:
        request: Pedido entrante.

    Returns:
        ``True`` si el esquema es https.
    """
    return request.url.scheme == "https"


def _back_to_app(reason: str) -> RedirectResponse:
    """Vuelve a la app con el motivo del rechazo en la query.

    El callback lo abre un navegador, no un cliente de API: contestarle un JSON
    de error lo dejaria mirando texto crudo sin forma de volver. Se lo manda de
    vuelta a la pantalla de login, que traduce el codigo a un mensaje.

    Args:
        reason: Codigo del motivo (lo interpreta el frontend).

    Returns:
        Redirect a la raiz con `?auth_error=<reason>`.
    """
    return RedirectResponse(
        f"/?auth_error={reason}", status_code=status.HTTP_303_SEE_OTHER
    )


def _login_disabled() -> HTTPException:
    """Error uniforme cuando el login no esta configurado.

    Returns:
        `HTTPException` 404 lista para lanzar.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "auth_disabled",
            "message": "ログインは設定されていません。",
            "details": {},
        },
    )


@router.get("/status", response_model=AuthStatus)
def auth_status(
    request: Request, settings: Settings = Depends(get_settings)
) -> AuthStatus:
    """Informa si hay login activo y si este pedido esta autenticado.

    Args:
        request: Pedido entrante (para leer la cookie).
        settings: Settings de la aplicacion.

    Returns:
        `AuthStatus` para que el frontend decida que mostrar.
    """
    if not is_auth_configured(settings):
        return AuthStatus(enabled=False, authenticated=True, email=None)
    token = request.cookies.get(SESSION_COOKIE)
    email = read_session(token, settings=settings) if token else None
    return AuthStatus(enabled=True, authenticated=email is not None, email=email)


@router.get("/login")
def auth_login(
    request: Request, settings: Settings = Depends(get_settings)
) -> RedirectResponse:
    """Manda al usuario a Google a elegir su cuenta.

    Args:
        request: Pedido entrante.
        settings: Settings de la aplicacion.

    Returns:
        Redirect al endpoint de autorizacion de Google.

    Raises:
        HTTPException: 404 si el login no esta configurado; 500 si falla armar
            la URL de autorizacion.
    """
    if not is_auth_configured(settings):
        raise _login_disabled()
    try:
        signed_state, nonce = issue_state(settings=settings)
        payload = read_state(signed_state, settings=settings)
        if payload is None:  # pragma: no cover — recien firmado, siempre valida.
            raise AuthError("No se pudo firmar el state.")
        url = build_authorization_url(
            settings=settings,
            redirect_uri=_redirect_uri(request),
            state=payload["state"],
            nonce=nonce,
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "auth_misconfigured", "message": str(exc), "details": {}},
        ) from exc

    response = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    response.set_cookie(
        STATE_COOKIE,
        signed_state,
        max_age=STATE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
        path="/",
    )
    return response


@router.get("/callback", name="auth_callback")
def auth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Recibe la vuelta de Google, valida todo y abre la sesion.

    Args:
        request: Pedido entrante (cookies + host).
        code: Codigo de autorizacion de Google.
        state: `state` que Google devuelve.
        error: Error que Google reporta (ej. el usuario cancelo).
        settings: Settings de la aplicacion.

    Returns:
        Redirect a la raiz de la app: con la cookie de sesion si todo valido, o
        con `?auth_error=<motivo>` si el login se rechazo.

    Raises:
        HTTPException: 404 si el login no esta configurado.
    """
    if not is_auth_configured(settings):
        raise _login_disabled()

    if error:
        logger.info("Login cancelado en Google: %s", error)
        return _back_to_app("cancelled")

    cookie = request.cookies.get(STATE_COOKIE)
    payload = read_state(cookie, settings=settings) if cookie else None
    # `state` ausente, vencido o distinto = el login no lo empezo esta persona.
    if payload is None or not state or state != payload["state"]:
        logger.warning("Login rechazado: state invalido o vencido.")
        return _back_to_app("state_invalid")
    if not code:
        return _back_to_app("no_code")

    try:
        identity = exchange_code(
            settings=settings,
            code=code,
            redirect_uri=_redirect_uri(request),
            nonce=payload["nonce"],
        )
    except AuthError as exc:
        logger.warning("Login rechazado: %s", exc)
        return _back_to_app("failed")

    # El candado que importa: estar en Google no alcanza, hay que estar en la
    # allowlist. Se loguea el intento para que un acceso ajeno deje rastro.
    if not is_email_allowed(identity.email, settings):
        logger.warning("Login denegado (fuera de la allowlist): %s", identity.email)
        return _back_to_app("not_allowed")

    logger.info("Login OK: %s", identity.email)
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(identity.email, settings=settings),
        max_age=settings.auth_session_max_age,
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
        path="/",
    )
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def auth_logout(request: Request, response: Response) -> None:
    """Cierra la sesion borrando la cookie.

    Args:
        request: Pedido entrante.
        response: Respuesta donde borrar la cookie.
    """
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(STATE_COOKIE, path="/")
