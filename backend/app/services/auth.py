"""Login con Google (OAuth 2.0 authorization code) y sesion firmada.

La app es de un solo usuario y sus datos son fiscales: マイナンバー, ingresos,
recibos. El modelo de seguridad tiene DOS candados, y el segundo es el que
importa:

1. Google verifica **quien** es el que entra.
2. `auth_allowed_emails` decide **si esa persona puede entrar**. "Iniciar sesion
   con Google" no autoriza nada por si solo: cualquiera del planeta tiene una
   cuenta de Google. Sin allowlist el login queda deshabilitado a proposito.

Si se habilita el login y falta configuración, la aplicación no arranca.

La sesion es una cookie firmada (`itsdangerous`) con el email y un vencimiento;
no se guarda estado en el servidor, que para un solo usuario es lo mas simple
que funciona.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import Settings

logger = logging.getLogger(__name__)

AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
# Emisores validos del id_token de Google (acepta las dos formas historicas).
_VALID_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
_SCOPES = "openid email profile"
_HTTP_TIMEOUT = 20
# Ventana de vida del `state` del flujo OAuth (el ida y vuelta a Google).
STATE_MAX_AGE = 600

SESSION_COOKIE = "kakutei_session"
STATE_COOKIE = "kakutei_oauth_state"
_SESSION_SALT = "kakutei-session-v1"
_STATE_SALT = "kakutei-oauth-state-v1"


class AuthError(Exception):
    """Falla del flujo de login (configuracion, Google o autorizacion)."""


@dataclass(frozen=True)
class GoogleIdentity:
    """Identidad devuelta por Google en el `id_token`.

    Args:
        subject: Id estable del usuario en Google (``sub``).
        email: Direccion verificada.
        name: Nombre para mostrar, si vino.
        picture: URL del avatar, si vino.
    """

    subject: str
    email: str
    name: str | None = None
    picture: str | None = None


def is_auth_configured(settings: Settings) -> bool:
    """Indica si el login esta prendido Y completamente configurado.

    Falta de configuración devuelve False; el arranque rechaza AUTH_ENABLED
    si falta el client id, el secret, la clave de firma o la allowlist.

    Args:
        settings: Settings de la aplicacion.

    Returns:
        ``True`` si se puede exigir y procesar un login con Google.
    """
    return bool(
        settings.auth_enabled
        and settings.auth_google_client_id
        and settings.auth_google_client_secret
        and settings.auth_secret_key
        and settings.auth_allowed_emails
    )


def normalize_email(email: str) -> str:
    """Normaliza una direccion para compararla contra la allowlist.

    Args:
        email: Direccion tal como vino.

    Returns:
        La direccion en minusculas y sin espacios alrededor.
    """
    return email.strip().lower()


def is_email_allowed(email: str, settings: Settings) -> bool:
    """Indica si la direccion esta en la allowlist.

    Args:
        email: Direccion verificada por Google.
        settings: Settings con `auth_allowed_emails`.

    Returns:
        ``True`` si esa direccion puede entrar.
    """
    allowed = {normalize_email(item) for item in settings.auth_allowed_emails}
    return normalize_email(email) in allowed


def _serializer(settings: Settings, salt: str) -> URLSafeTimedSerializer:
    """Crea el serializador firmado para cookies.

    Args:
        settings: Settings con `auth_secret_key`.
        salt: Sal que separa los usos (sesion vs state).

    Returns:
        Serializador listo para firmar/verificar.

    Raises:
        AuthError: Si no hay clave de firma configurada.
    """
    if not settings.auth_secret_key:
        raise AuthError("Falta AUTH_SECRET_KEY para firmar la sesion.")
    return URLSafeTimedSerializer(settings.auth_secret_key, salt=salt)


def issue_session(email: str, *, settings: Settings) -> str:
    """Emite el token de sesion firmado para una direccion ya autorizada.

    Args:
        email: Direccion autorizada.
        settings: Settings de la aplicacion.

    Returns:
        Token firmado para poner en la cookie.
    """
    return _serializer(settings, _SESSION_SALT).dumps({"email": normalize_email(email)})


def read_session(token: str, *, settings: Settings) -> str | None:
    """Valida el token de sesion y devuelve la direccion, si sigue vigente.

    Revalida la allowlist en cada request y no solo al entrar: sacar una
    direccion de `auth_allowed_emails` tiene que cortar el acceso ya, sin
    esperar a que venza la cookie.

    Args:
        token: Contenido de la cookie de sesion.
        settings: Settings de la aplicacion.

    Returns:
        La direccion autenticada, o ``None`` si el token es invalido, vencio o
        la direccion ya no esta autorizada.
    """
    try:
        payload = _serializer(settings, _SESSION_SALT).loads(
            token, max_age=settings.auth_session_max_age
        )
    except (BadSignature, SignatureExpired, AuthError):
        return None
    if not isinstance(payload, dict):
        return None
    email = payload.get("email")
    if not isinstance(email, str) or not is_email_allowed(email, settings):
        return None
    return email


def issue_state(*, settings: Settings) -> tuple[str, str]:
    """Genera el `state` y el `nonce` del flujo OAuth.

    El `state` viaja firmado en una cookie de vida corta y se compara al volver:
    es lo que impide que alguien te haga completar un login que no empezaste
    (CSRF). El `nonce` viaja dentro del `id_token` y ata la respuesta de Google
    a este pedido en concreto.

    Args:
        settings: Settings de la aplicacion.

    Returns:
        Tupla ``(cookie_firmada, nonce)``.
    """
    nonce = secrets.token_urlsafe(24)
    state = secrets.token_urlsafe(24)
    signed = _serializer(settings, _STATE_SALT).dumps({"state": state, "nonce": nonce})
    return signed, nonce


def read_state(cookie: str, *, settings: Settings) -> dict[str, str] | None:
    """Valida la cookie de `state` del flujo OAuth.

    Args:
        cookie: Contenido de la cookie de state.
        settings: Settings de la aplicacion.

    Returns:
        Diccionario con ``state`` y ``nonce``, o ``None`` si no valida.
    """
    try:
        payload = _serializer(settings, _STATE_SALT).loads(cookie, max_age=STATE_MAX_AGE)
    except (BadSignature, SignatureExpired, AuthError):
        return None
    if not isinstance(payload, dict):
        return None
    state = payload.get("state")
    nonce = payload.get("nonce")
    if not isinstance(state, str) or not isinstance(nonce, str):
        return None
    return {"state": state, "nonce": nonce}


def state_value(cookie_payload: dict[str, str]) -> str:
    """Extrae el `state` que hay que mandarle a Google.

    Args:
        cookie_payload: Payload devuelto por `read_state` / `issue_state`.

    Returns:
        El valor de `state`.
    """
    return cookie_payload["state"]


def build_authorization_url(
    *, settings: Settings, redirect_uri: str, state: str, nonce: str
) -> str:
    """Arma la URL de Google a la que se manda al usuario para que entre.

    Args:
        settings: Settings con el client id.
        redirect_uri: URL de vuelta (tiene que estar registrada en Google).
        state: Valor anti-CSRF.
        nonce: Valor que Google devuelve dentro del `id_token`.

    Returns:
        URL completa del endpoint de autorizacion.

    Raises:
        AuthError: Si falta el client id.
    """
    if not settings.auth_google_client_id:
        raise AuthError("Falta AUTH_GOOGLE_CLIENT_ID.")
    params = {
        "client_id": settings.auth_google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _SCOPES,
        "state": state,
        "nonce": nonce,
        # Sin refresh token: la sesion la maneja la cookie, no hace falta pedir
        # acceso offline ni guardar credenciales de Google.
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{AUTHORIZE_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _post_form(url: str, data: dict[str, str]) -> dict[str, object]:
    """Hace un POST form-urlencoded y devuelve el JSON de respuesta.

    Args:
        url: Endpoint destino.
        data: Campos del formulario.

    Returns:
        Respuesta decodificada.

    Raises:
        AuthError: Si la llamada falla o la respuesta no es JSON.
    """
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 — URL fija de Google, no del usuario.
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise AuthError(f"Google rechazo el intercambio de codigo: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AuthError(f"No se pudo contactar a Google: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AuthError("Google devolvio una respuesta ilegible.") from exc
    if not isinstance(payload, dict):
        raise AuthError("Google devolvio una respuesta inesperada.")
    return payload


def _decode_id_token_claims(id_token: str) -> dict[str, object]:
    """Decodifica el payload del `id_token` (JWT) sin verificar la firma.

    No hace falta verificar la firma **en este flujo puntual**: el token no vino
    del navegador sino de una llamada server-to-server al endpoint de tokens de
    Google sobre TLS, asi que el canal ya garantiza el origen (es lo que la
    propia documentacion de Google admite para el authorization code flow). Lo
    que si se valida, en `verify_id_token`, es el contenido: emisor, destinatario
    y nonce.

    Args:
        id_token: JWT compacto devuelto por Google.

    Returns:
        Claims del token.

    Raises:
        AuthError: Si el token no tiene forma de JWT o no decodifica.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise AuthError("El id_token de Google no tiene formato JWT.")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (binascii.Error, ValueError) as exc:
        raise AuthError("No se pudo leer el id_token de Google.") from exc
    if not isinstance(claims, dict):
        raise AuthError("El id_token de Google no trae claims.")
    return claims


def verify_id_token(
    claims: dict[str, object], *, settings: Settings, nonce: str
) -> GoogleIdentity:
    """Valida los claims del `id_token` y arma la identidad.

    Chequea emisor, destinatario (`aud` = nuestro client id), `nonce` y que el
    email este verificado por Google. Un token valido de OTRA aplicacion no
    sirve para entrar acá: por eso se compara `aud`.

    Args:
        claims: Claims decodificados.
        settings: Settings con el client id.
        nonce: Nonce que se mando en la autorizacion.

    Returns:
        `GoogleIdentity` con el email verificado.

    Raises:
        AuthError: Si algun chequeo falla.
    """
    if claims.get("iss") not in _VALID_ISSUERS:
        raise AuthError("El id_token no lo emitio Google.")
    if claims.get("aud") != settings.auth_google_client_id:
        raise AuthError("El id_token es de otra aplicacion.")
    if claims.get("nonce") != nonce:
        raise AuthError("El id_token no corresponde a este intento de login.")
    if claims.get("email_verified") not in (True, "true"):
        raise AuthError("Google no tiene esa direccion como verificada.")

    email = claims.get("email")
    subject = claims.get("sub")
    if not isinstance(email, str) or not isinstance(subject, str):
        raise AuthError("El id_token no trae email o sub.")

    name = claims.get("name")
    picture = claims.get("picture")
    return GoogleIdentity(
        subject=subject,
        email=normalize_email(email),
        name=name if isinstance(name, str) else None,
        picture=picture if isinstance(picture, str) else None,
    )


def exchange_code(
    *, settings: Settings, code: str, redirect_uri: str, nonce: str
) -> GoogleIdentity:
    """Canjea el `code` de Google por la identidad del usuario.

    Args:
        settings: Settings con las credenciales OAuth.
        code: Codigo de autorizacion devuelto por Google.
        redirect_uri: El MISMO redirect_uri usado al autorizar.
        nonce: Nonce del intento de login.

    Returns:
        `GoogleIdentity` verificada.

    Raises:
        AuthError: Si falta configuracion, Google rechaza el canje o el token
            no valida.
    """
    if not (settings.auth_google_client_id and settings.auth_google_client_secret):
        raise AuthError("Faltan las credenciales OAuth de Google.")

    payload = _post_form(
        TOKEN_ENDPOINT,
        {
            "code": code,
            "client_id": settings.auth_google_client_id,
            "client_secret": settings.auth_google_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    id_token = payload.get("id_token")
    if not isinstance(id_token, str):
        raise AuthError("Google no devolvio un id_token.")

    claims = _decode_id_token_claims(id_token)
    return verify_id_token(claims, settings=settings, nonce=nonce)
