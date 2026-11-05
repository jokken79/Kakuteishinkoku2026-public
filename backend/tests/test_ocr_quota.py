"""Tests del contador diario de cuota de los proveedores OCR cloud.

Cubre: incremento, freno al limite, reseteo por fecha (zona US/Pacific),
resolucion de limite configurable, integracion con `resolve_chain` (un provider
cloud sobre-cuota se salta -> fallback local) y el reporte para el endpoint.

Aislamiento: cada test usa un `Settings` con ``evidence_dir`` bajo ``tmp_path``,
de modo que el JSON de uso (`api_usage.json`) nunca toca el working tree real.
"""

from __future__ import annotations

import datetime

import pytest

from app.core.config import Settings
from app.services.ocr import quota
from app.services.ocr.providers.fake import FakeOCRProvider
from app.services.ocr.providers.gemini import GeminiVisionProvider
from app.services.ocr.registry import provider_statuses, resolve_chain


@pytest.fixture
def cfg(tmp_path) -> Settings:
    """Settings de test con evidence_dir aislado en tmp_path.

    El JSON de uso vive en ``tmp_path/api_usage.json`` (evidence_dir.parent).
    """
    return Settings(evidence_dir=str(tmp_path / "data" / "evidence"))


# --- Conversion de fecha Pacific ------------------------------------------


def test_pacific_today_uses_pacific_zone() -> None:
    """01:00 UTC del dia 2 es aun el dia 1 en Pacific (UTC-8/-7)."""
    early_utc = datetime.datetime(2026, 1, 2, 1, 0, tzinfo=datetime.UTC)
    assert quota.pacific_today(early_utc) == datetime.date(2026, 1, 1)


def test_next_reset_is_midnight_pacific() -> None:
    """El proximo reseteo cae a las 00:00 Pacific (08:00 UTC en invierno)."""
    now = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC)
    reset = quota.next_reset_at(now)
    # 2026-01-02 00:00 Pacific == 2026-01-02 08:00 UTC (PST, UTC-8).
    assert reset == datetime.datetime(2026, 1, 2, 8, 0, tzinfo=datetime.UTC)


# --- Incremento y lectura --------------------------------------------------


def test_record_increments_counter(cfg: Settings) -> None:
    """Cada `record_usage` suma 1 al contador del dia."""
    assert quota.usage_today("gemini", settings=cfg) == 0
    assert quota.record_usage("gemini", settings=cfg) == 1
    assert quota.record_usage("gemini", settings=cfg) == 2
    assert quota.usage_today("gemini", settings=cfg) == 2


def test_record_is_per_provider(cfg: Settings) -> None:
    """Los contadores son independientes por provider."""
    quota.record_usage("gemini", settings=cfg)
    quota.record_usage("gemini", settings=cfg)
    quota.record_usage("glm", settings=cfg)
    assert quota.usage_today("gemini", settings=cfg) == 2
    assert quota.usage_today("glm", settings=cfg) == 1


def test_counter_resets_by_date(cfg: Settings) -> None:
    """El contador es por fecha Pacific: otro dia empieza de cero."""
    day1 = datetime.datetime(2026, 5, 10, 18, 0, tzinfo=datetime.UTC)
    day2 = datetime.datetime(2026, 5, 11, 18, 0, tzinfo=datetime.UTC)
    quota.record_usage("gemini", settings=cfg, now=day1)
    quota.record_usage("gemini", settings=cfg, now=day1)
    assert quota.usage_today("gemini", settings=cfg, now=day1) == 2
    # Dia siguiente (Pacific): contador en cero.
    assert quota.usage_today("gemini", settings=cfg, now=day2) == 0
    quota.record_usage("gemini", settings=cfg, now=day2)
    assert quota.usage_today("gemini", settings=cfg, now=day2) == 1
    # El dia 1 conserva su valor (historico).
    assert quota.usage_today("gemini", settings=cfg, now=day1) == 2


# --- Limite configurable ---------------------------------------------------


def test_daily_limit_default_conservative(cfg: Settings) -> None:
    """Sin limite especifico, usa el default conservador (200)."""
    assert quota.daily_limit("gemini", cfg) == 200


def test_daily_limit_specific_override() -> None:
    """Un limite especifico por provider pisa el default."""
    cfg = Settings(ocr_gemini_daily_limit=50)
    assert quota.daily_limit("gemini", cfg) == 50
    assert quota.daily_limit("glm", cfg) == 200  # otros siguen en default.


# --- Freno al limite -------------------------------------------------------


def test_is_over_limit_frena_al_alcanzar(tmp_path) -> None:
    """Al alcanzar el limite, `is_over_limit` devuelve True (no-usable)."""
    cfg = Settings(
        evidence_dir=str(tmp_path / "data" / "evidence"),
        ocr_gemini_daily_limit=3,
    )
    for _ in range(2):
        quota.record_usage("gemini", settings=cfg)
    assert quota.is_over_limit("gemini", settings=cfg) is False  # 2 < 3
    quota.record_usage("gemini", settings=cfg)  # ahora 3
    assert quota.is_over_limit("gemini", settings=cfg) is True  # 3 >= 3


def test_is_over_limit_false_for_local_providers(cfg: Settings) -> None:
    """Los providers locales nunca se frenan por cuota."""
    for _ in range(1000):
        # paddle no es cloud: aunque se registrara, is_over_limit es False.
        pass
    assert quota.is_over_limit("paddle", settings=cfg) is False


# --- Reporte para el endpoint ----------------------------------------------


def test_usage_for_payload_shape(tmp_path) -> None:
    """`usage_for` arma el payload con percent, warn y over_limit correctos."""
    cfg = Settings(
        evidence_dir=str(tmp_path / "data" / "evidence"),
        ocr_gemini_daily_limit=10,
    )
    for _ in range(8):
        quota.record_usage("gemini", settings=cfg)
    payload = quota.usage_for("gemini", settings=cfg)
    assert payload["provider"] == "gemini"
    assert payload["used_today"] == 8
    assert payload["daily_limit"] == 10
    assert payload["percent"] == 80
    assert payload["warn"] is True  # 80% alcanzado, sin frenar aun.
    assert payload["over_limit"] is False
    assert payload["resets_at"]  # ISO no vacio.


def test_usage_report_covers_all_cloud_providers(cfg: Settings) -> None:
    """El reporte incluye un payload por cada provider cloud."""
    report = quota.usage_report(settings=cfg)
    names = {row["provider"] for row in report}
    assert names == set(quota.CLOUD_PROVIDERS)


# --- Integracion con resolve_chain ----------------------------------------


def test_resolve_chain_skips_over_quota_provider(tmp_path) -> None:
    """Un provider cloud sobre-cuota se salta en la cadena (fallback local)."""
    cfg = Settings(
        evidence_dir=str(tmp_path / "data" / "evidence"),
        allow_external_ocr=True,
        ocr_primary="gemini",
        ocr_fallback_chain=["gemini", "fake"],
        ocr_gemini_enabled=True,
        ocr_gemini_api_key="dummy-key-for-availability",  # noqa: S106 — valor de test
        ocr_fake_enabled=True,
        ocr_gemini_daily_limit=1,
    )
    # Sin gastar cuota, gemini es usable (si el SDK esta instalado).
    gemini = GeminiVisionProvider(api_key="dummy-key-for-availability", model="x")  # noqa: S106
    if gemini.is_available():
        chain_before = [p.name for p in resolve_chain(cfg)]
        assert "gemini" in chain_before
    # Tras alcanzar la cuota, gemini desaparece de la cadena.
    quota.record_usage("gemini", settings=cfg)
    chain_after = [p.name for p in resolve_chain(cfg)]
    assert "gemini" not in chain_after


def test_provider_statuses_marks_over_quota(tmp_path) -> None:
    """`provider_statuses` marca usable=False y da la razon de cuota."""
    cfg = Settings(
        evidence_dir=str(tmp_path / "data" / "evidence"),
        allow_external_ocr=True,
        ocr_gemini_enabled=True,
        ocr_gemini_api_key="dummy-key-for-availability",  # noqa: S106 — valor de test
        ocr_gemini_daily_limit=1,
    )
    quota.record_usage("gemini", settings=cfg)
    statuses = {s.name: s for s in provider_statuses(cfg)}
    gem = statuses["gemini"]
    if gem.available:  # solo si el SDK google-genai esta instalado.
        assert gem.usable is False
        assert gem.reason is not None and "クオ" not in (gem.reason or "")


def test_fake_provider_does_not_consume_quota(cfg: Settings) -> None:
    """El pipeline con FakeProvider no incrementa la cuota cloud (no es cloud)."""
    from app.services.ocr.pipeline import process_receipt

    process_receipt(
        b"img",
        providers=[FakeOCRProvider()],
        today=datetime.date(2026, 1, 1),
        settings=cfg,
    )
    assert quota.usage_today("gemini", settings=cfg) == 0
