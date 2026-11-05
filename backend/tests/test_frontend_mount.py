"""Tests del montaje de la PWA en el backend (un solo proceso, un solo origen).

Lo que se protege: que servir el frontend NO se coma las rutas de `/api/v1`, y
que sin build el backend siga levantando igual (desarrollo con Vite).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app, resolve_frontend_dist


def _make_dist(tmp_path: Path) -> Path:
    """Crea un build de PWA minimo (index.html + un asset).

    Args:
        tmp_path: Carpeta temporal del test.

    Returns:
        Ruta al `dist` creado.
    """
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>確定申告</title>", encoding="utf-8")
    (dist / "sw.js").write_text("// service worker", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text('{"name":"確定申告"}', encoding="utf-8")
    return dist


def test_sirve_la_pwa_sin_pisar_la_api(tmp_path: Path) -> None:
    """Con build presente, `/` devuelve la PWA y `/api/v1` sigue respondiendo."""
    get_settings.cache_clear()
    settings = get_settings()
    settings.frontend_dist = str(_make_dist(tmp_path))
    try:
        client = TestClient(create_app())

        index = client.get("/")
        assert index.status_code == 200
        assert "確定申告" in index.text
        assert index.headers["cache-control"] == "no-cache"
        assert client.get("/index.html").headers["cache-control"] == "no-cache"
        assert client.get("/sw.js").headers["cache-control"] == "no-cache"

        # La razon de ser del mount: que la API no quede tapada.
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "cache-control" not in asset.headers
        # El manifest en la raiz es lo que hace instalable la PWA en el celular.
        assert client.get("/manifest.webmanifest").status_code == 200
    finally:
        get_settings.cache_clear()


def test_sin_build_el_backend_levanta_igual(tmp_path: Path) -> None:
    """Sin build (desarrollo con Vite), la API funciona y `/` no existe."""
    get_settings.cache_clear()
    settings = get_settings()
    settings.frontend_dist = str(tmp_path / "no-existe")
    try:
        client = TestClient(create_app())
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/").status_code == 404
    finally:
        get_settings.cache_clear()


def test_resolve_frontend_dist_descarta_carpeta_sin_index(tmp_path: Path) -> None:
    """Una carpeta sin `index.html` no es un build servible."""
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    settings = Settings(frontend_dist=str(vacia))
    assert resolve_frontend_dist(settings) is None


def test_resolve_frontend_dist_acepta_build_valido(tmp_path: Path) -> None:
    """Una carpeta con `index.html` si se sirve."""
    dist = _make_dist(tmp_path)
    settings = Settings(frontend_dist=str(dist))
    assert resolve_frontend_dist(settings) == dist
