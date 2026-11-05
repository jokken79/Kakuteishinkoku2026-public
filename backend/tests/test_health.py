"""Tests del endpoint de healthcheck."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    """El healthcheck devuelve 200 con el payload esperado."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "service": "kakuteishinkoku",
        "version": "0.1.0",
    }
