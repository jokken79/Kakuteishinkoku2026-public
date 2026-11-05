"""Tests del login con Google.

El foco esta en los modos de falla peligrosos, no en el camino feliz:

- que sin configuracion completa el login quede APAGADO, no abierto;
- que una cuenta de Google valida pero fuera de la allowlist NO entre;
- que un `id_token` de otra aplicacion o de otro intento de login NO sirva;
- que sacar a alguien de la allowlist le corte el acceso al instante;
- que con el login activo la API entera quede cerrada salvo health y auth.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import create_app, requires_auth
from app.models import Base, FiscalYear, Taxpayer
from app.services.auth import (
    SESSION_COOKIE,
    STATE_COOKIE,
    AuthError,
    GoogleIdentity,
    is_auth_configured,
    is_email_allowed,
    issue_session,
    issue_state,
    read_session,
    read_state,
    verify_id_token,
)

OWNER = "duenio@example.com"
CLIENT_ID = "client-id-de-prueba.apps.googleusercontent.com"


def _settings(**overrides: Any) -> Settings:
    """Settings con el login configurado y funcionando.

    Args:
        **overrides: Campos a pisar.

    Returns:
        `Settings` listo para los tests de auth.
    """
    base: dict[str, Any] = {
        "auth_enabled": True,
        "auth_google_client_id": CLIENT_ID,
        "auth_google_client_secret": "secreto",
        "auth_allowed_emails": [OWNER],
        "auth_secret_key": "clave-de-firma-de-prueba",
    }
    base.update(overrides)
    return Settings(**base)


def _claims(**overrides: Any) -> dict[str, Any]:
    """Claims de un `id_token` valido de Google.

    Args:
        **overrides: Claims a pisar.

    Returns:
        Diccionario de claims.
    """
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": OWNER,
        "email_verified": True,
        "nonce": "nonce-de-prueba",
        "name": "田中太郎",
    }
    claims.update(overrides)
    return claims


# --- Configuracion: fail-closed -------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("auth_enabled", False),
        ("auth_google_client_id", None),
        ("auth_google_client_secret", None),
        ("auth_secret_key", None),
        ("auth_allowed_emails", []),
    ],
)
def test_config_incompleta_apaga_el_login(field: str, value: Any) -> None:
    """Falta cualquier pieza -> el login queda apagado, nunca abierto.

    El caso critico es `auth_allowed_emails` vacio: un login activo sin
    allowlist dejaria entrar a cualquier cuenta de Google del mundo.
    """
    assert is_auth_configured(_settings(**{field: value})) is False


def test_config_completa_prende_el_login() -> None:
    """Con todo configurado, el login esta activo."""
    assert is_auth_configured(_settings()) is True


# --- Allowlist -------------------------------------------------------------


def test_allowlist_ignora_mayusculas_y_espacios() -> None:
    """La comparacion normaliza, para que un typo de formato no deje afuera."""
    settings = _settings(auth_allowed_emails=["  DUENIO@Example.com "])
    assert is_email_allowed(OWNER, settings) is True
    assert is_email_allowed("Duenio@EXAMPLE.COM", settings) is True


def test_allowlist_rechaza_a_cualquier_otro() -> None:
    """Tener cuenta de Google no alcanza para entrar."""
    assert is_email_allowed("otro@gmail.com", _settings()) is False


# --- id_token --------------------------------------------------------------


def test_id_token_valido_devuelve_la_identidad() -> None:
    """Un token bien formado y dirigido a esta app produce la identidad."""
    identity = verify_id_token(
        _claims(), settings=_settings(), nonce="nonce-de-prueba"
    )
    assert isinstance(identity, GoogleIdentity)
    assert identity.email == OWNER
    assert identity.name == "田中太郎"


@pytest.mark.parametrize(
    ("overrides", "motivo"),
    [
        ({"iss": "https://evil.example.com"}, "emisor ajeno"),
        ({"aud": "otra-app.apps.googleusercontent.com"}, "token de otra app"),
        ({"nonce": "otro-nonce"}, "otro intento de login"),
        ({"email_verified": False}, "email sin verificar"),
        ({"email": None}, "sin email"),
    ],
)
def test_id_token_invalido_se_rechaza(overrides: dict[str, Any], motivo: str) -> None:
    """Cada chequeo del `id_token` corta el login.

    El de `aud` es el que impide reusar un token valido emitido para OTRA
    aplicacion; el de `nonce`, reusar uno de otro intento.
    """
    with pytest.raises(AuthError):
        verify_id_token(
            _claims(**overrides), settings=_settings(), nonce="nonce-de-prueba"
        )
    assert motivo  # el motivo documenta el caso en el reporte de pytest


def test_email_normalizado_al_verificar() -> None:
    """El email queda normalizado para que la sesion compare siempre igual."""
    identity = verify_id_token(
        _claims(email="DUENIO@Example.com"),
        settings=_settings(),
        nonce="nonce-de-prueba",
    )
    assert identity.email == OWNER


# --- Sesion ----------------------------------------------------------------


def test_sesion_ida_y_vuelta() -> None:
    """Un token recien emitido devuelve la direccion."""
    settings = _settings()
    assert read_session(issue_session(OWNER, settings=settings), settings=settings) == OWNER


def test_sesion_con_firma_ajena_no_vale() -> None:
    """Una cookie firmada con otra clave no abre la puerta."""
    token = issue_session(OWNER, settings=_settings(auth_secret_key="otra-clave"))
    assert read_session(token, settings=_settings()) is None


def test_sesion_vencida_no_vale() -> None:
    """Pasado el plazo, la sesion deja de servir."""
    settings = _settings()
    token = issue_session(OWNER, settings=settings)
    assert read_session(token, settings=_settings(auth_session_max_age=-1)) is None
    assert read_session(token, settings=settings) == OWNER


def test_sacar_de_la_allowlist_corta_el_acceso_ya() -> None:
    """Revocar es inmediato: no hay que esperar a que venza la cookie.

    Es la unica forma de cortar el acceso de una sesion ya emitida, porque no
    hay estado de sesion en el servidor.
    """
    settings = _settings()
    token = issue_session(OWNER, settings=settings)
    revocado = _settings(auth_allowed_emails=["otra@example.com"])
    assert read_session(token, settings=revocado) is None


def test_state_ida_y_vuelta_y_firma() -> None:
    """El `state` firmado valida, y uno firmado con otra clave no."""
    settings = _settings()
    signed, nonce = issue_state(settings=settings)
    payload = read_state(signed, settings=settings)
    assert payload is not None
    assert payload["nonce"] == nonce
    assert read_state(signed, settings=_settings(auth_secret_key="otra")) is None


# --- Rutas protegidas ------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/api/v1/health", "/api/v1/auth/status", "/api/v1/auth/login", "/", "/assets/x.js"],
)
def test_rutas_publicas(path: str) -> None:
    """Health, auth y la PWA estatica quedan accesibles sin sesion."""
    assert requires_auth(path, "/api/v1") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/receipts",
        "/api/v1/tax/calculate",
        "/api/v1/filing/x/official-package",
        "/api/v1/health/../receipts",
        "/docs",
        "/openapi.json",
    ],
)
def test_rutas_protegidas(path: str) -> None:
    """Todo lo demas — incluida la documentacion de la API — exige sesion."""
    assert requires_auth(path, "/api/v1") is True


# --- Integracion con la app ------------------------------------------------


@pytest.fixture
def client_con_login(tmp_path) -> Generator[TestClient, None, None]:
    """App con el login activo y una BD en memoria.

    Yields:
        `TestClient` de una app con login configurado.
    """
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    db: Session = factory()
    taxpayer = Taxpayer(name="テスト太郎")
    db.add(taxpayer)
    db.flush()
    db.add(
        FiscalYear(taxpayer_id=taxpayer.id, year=2025, rules_ref="tax_rules/2025.json")
    )
    db.commit()
    db.close()

    get_settings.cache_clear()
    settings = get_settings()
    settings.auth_enabled = True
    settings.auth_google_client_id = CLIENT_ID
    settings.auth_google_client_secret = "secreto"
    settings.auth_allowed_emails = [OWNER]
    settings.auth_secret_key = "clave-de-firma-de-prueba"
    settings.frontend_dist = str(tmp_path / "sin-build")

    app = create_app()

    def _override_get_db() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_api_cerrada_sin_sesion(client_con_login: TestClient) -> None:
    """Con login activo, la API responde 401 con un codigo que la UI entiende."""
    response = client_con_login.get("/api/v1/receipts")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "auth_required"


def test_health_y_status_siguen_abiertos(client_con_login: TestClient) -> None:
    """Sin ellos el frontend no podria ni mostrar la pantalla de login."""
    assert client_con_login.get("/api/v1/health").status_code == 200
    status_body = client_con_login.get("/api/v1/auth/status").json()
    assert status_body == {"enabled": True, "authenticated": False, "email": None}


def test_api_abierta_con_sesion_valida(client_con_login: TestClient) -> None:
    """Con la cookie de sesion, la API responde normalmente."""
    settings = get_settings()
    client_con_login.cookies.set(
        SESSION_COOKIE, issue_session(OWNER, settings=settings)
    )

    assert client_con_login.get("/api/v1/receipts").status_code == 200
    status_body = client_con_login.get("/api/v1/auth/status").json()
    assert status_body["authenticated"] is True
    assert status_body["email"] == OWNER


def test_sesion_de_cuenta_no_autorizada_no_abre_nada(
    client_con_login: TestClient,
) -> None:
    """Una cookie bien firmada pero de otra cuenta no sirve.

    Cubre el caso de una direccion que estuvo autorizada y se saco de la lista.
    """
    settings = get_settings()
    client_con_login.cookies.set(
        SESSION_COOKIE, issue_session("intruso@example.com", settings=settings)
    )
    assert client_con_login.get("/api/v1/receipts").status_code == 401


def test_login_redirige_a_google_con_state(client_con_login: TestClient) -> None:
    """`/auth/login` manda a Google y deja el `state` firmado en una cookie."""
    response = client_con_login.get("/api/v1/auth/login", follow_redirects=False)

    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert f"client_id={CLIENT_ID}" in location
    assert "response_type=code" in location
    assert STATE_COOKIE in response.cookies


def test_callback_sin_state_es_rechazado(client_con_login: TestClient) -> None:
    """Sin `state` valido no se canjea nada: es la defensa contra CSRF."""
    response = client_con_login.get(
        "/api/v1/auth/callback",
        params={"code": "x", "state": "inventado"},
        follow_redirects=False,
    )
    # Vuelve a la app con el motivo, en vez de dejar al navegador en un JSON.
    assert response.status_code == 303
    assert response.headers["location"] == "/?auth_error=state_invalid"
    assert SESSION_COOKIE not in response.cookies


def test_callback_con_cuenta_ajena_no_abre_sesion(
    client_con_login: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Google autentica a cualquiera; la allowlist es la que deja entrar.

    Se simula la respuesta del endpoint de tokens de Google para una cuenta
    valida que NO esta habilitada: tiene que rebotar sin abrir sesion.
    """
    settings = get_settings()
    signed, nonce = issue_state(settings=settings)
    payload = read_state(signed, settings=settings)
    assert payload is not None

    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
    body = (
        base64.urlsafe_b64encode(
            json.dumps(_claims(email="intruso@gmail.com", nonce=nonce)).encode()
        )
        .decode()
        .rstrip("=")
    )
    monkeypatch.setattr(
        "app.services.auth._post_form",
        lambda url, data: {"id_token": f"{header}.{body}.firma"},
    )

    client_con_login.cookies.set(STATE_COOKIE, signed)
    response = client_con_login.get(
        "/api/v1/auth/callback",
        params={"code": "codigo", "state": payload["state"]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?auth_error=not_allowed"
    # Lo unico que importa de verdad: NO se abrio sesion.
    assert SESSION_COOKIE not in response.cookies


def test_callback_con_el_dueno_abre_sesion(
    client_con_login: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El camino feliz: cuenta habilitada -> cookie de sesion y redirect."""
    settings = get_settings()
    signed, nonce = issue_state(settings=settings)
    payload = read_state(signed, settings=settings)
    assert payload is not None

    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
    body = (
        base64.urlsafe_b64encode(json.dumps(_claims(nonce=nonce)).encode())
        .decode()
        .rstrip("=")
    )
    monkeypatch.setattr(
        "app.services.auth._post_form",
        lambda url, data: {"id_token": f"{header}.{body}.firma"},
    )

    client_con_login.cookies.set(STATE_COOKIE, signed)
    response = client_con_login.get(
        "/api/v1/auth/callback",
        params={"code": "codigo", "state": payload["state"]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert read_session(response.cookies[SESSION_COOKIE], settings=settings) == OWNER


def test_logout_borra_la_sesion(client_con_login: TestClient) -> None:
    """Despues de salir, la API vuelve a estar cerrada."""
    settings = get_settings()
    client_con_login.cookies.set(
        SESSION_COOKIE, issue_session(OWNER, settings=settings)
    )
    assert client_con_login.get("/api/v1/receipts").status_code == 200

    assert client_con_login.post("/api/v1/auth/logout").status_code == 204
    client_con_login.cookies.clear()
    assert client_con_login.get("/api/v1/receipts").status_code == 401


def test_sin_login_configurado_la_api_sigue_abierta(tmp_path) -> None:
    """Sin configurar, nada cambia: la app anda como siempre en local."""
    get_settings.cache_clear()
    settings = get_settings()
    settings.auth_enabled = False
    settings.frontend_dist = str(tmp_path / "sin-build")
    try:
        client = TestClient(create_app())
        assert client.get("/api/v1/health").status_code == 200
        status_body = client.get("/api/v1/auth/status").json()
        assert status_body == {"enabled": False, "authenticated": True, "email": None}
        # Con el login apagado, `/auth/login` no existe (no hay a donde mandar).
        assert client.get("/api/v1/auth/login", follow_redirects=False).status_code == 404
    finally:
        get_settings.cache_clear()


def test_callback_cancelado_vuelve_a_la_app(client_con_login: TestClient) -> None:
    """Si el usuario cancela en Google, vuelve a la pantalla de login."""
    response = client_con_login.get(
        "/api/v1/auth/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?auth_error=cancelled"


def test_auth_enabled_with_incomplete_configuration_fails_closed() -> None:
    from fastapi import FastAPI

    from app.main import _install_auth_guard

    settings = _settings(auth_enabled=True, auth_google_client_secret=None)
    with pytest.raises(RuntimeError, match="AUTH_ENABLED"):
        _install_auth_guard(FastAPI(), settings)
