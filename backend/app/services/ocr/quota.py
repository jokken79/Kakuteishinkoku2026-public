"""Contador diario de cuota de los proveedores OCR cloud (free tier).

El owner usa el free tier de Gemini (y otros providers cloud) y NO quiere
excederse. Los limites del free tier varian por modelo y se resetean a
**medianoche en zona US/Pacific** (Google resetea su cuota diaria a las 00:00
Pacific). Este modulo cuenta las llamadas REALES a cada provider cloud por dia y
expone si el provider ya alcanzo su limite configurable.

Diseno (espejo de `runtime_settings.py`):

- Persistencia simple en disco (JSON), sin tabla ni migracion: el archivo
  ``api_usage.json`` vive junto a la carpeta de evidencia/data.
- Estructura: ``{provider: {date_iso: count}}`` con la fecha en zona Pacific.
- ``record_usage(provider)`` incrementa el contador del dia (atomico, con lock).
- ``usage_today(provider)`` lee el contador del dia actual (Pacific).
- ``daily_limit(provider)`` resuelve el limite configurable (env/config).
- ``is_over_limit(provider)`` indica si el provider quedo no-usable hoy.
- ``usage_report(...)`` arma el payload del endpoint ``GET /ocr/usage``.

Solo se cuentan los providers cloud (``CLOUD_PROVIDERS``): los locales (paddle,
GLM-Ollama) no consumen cuota externa. El incremento se dispara desde el punto
de extract REAL de cada provider cloud (ver providers/*.py), de modo que un
fallback local o un provider deshabilitado nunca suma al contador.
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Providers cloud que consumen cuota externa (free tier por dia). Los locales
# (paddle, glm en modo Ollama) no cuentan: no salen del equipo.
CLOUD_PROVIDERS: tuple[str, ...] = ("gemini", "glm", "azure", "google")

# Zona horaria de reseteo de la cuota: Google resetea a medianoche US/Pacific.
PACIFIC = ZoneInfo("America/Los_Angeles")

# Umbral de aviso (porcentaje del limite) para advertir antes de frenar.
WARN_THRESHOLD = 0.80

# Lock de proceso para escrituras atomicas del JSON.
_LOCK = threading.Lock()


def pacific_today(now: datetime.datetime | None = None) -> datetime.date:
    """Devuelve la fecha actual en zona US/Pacific (clave del contador diario).

    Args:
        now: Instante de referencia (aware o naive UTC). Si es ``None`` usa
            ``datetime.now(UTC)``.

    Returns:
        La fecha (``date``) en zona Pacific, que es cuando Google resetea la
        cuota.
    """
    if now is None:
        now = datetime.datetime.now(datetime.UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=datetime.UTC)
    return now.astimezone(PACIFIC).date()


def next_reset_at(now: datetime.datetime | None = None) -> datetime.datetime:
    """Devuelve el instante (UTC) del proximo reseteo de cuota (00:00 Pacific).

    Args:
        now: Instante de referencia. Si es ``None`` usa el actual.

    Returns:
        ``datetime`` aware en UTC de la proxima medianoche Pacific.
    """
    if now is None:
        now = datetime.datetime.now(datetime.UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=datetime.UTC)
    local = now.astimezone(PACIFIC)
    tomorrow = local.date() + datetime.timedelta(days=1)
    midnight = datetime.datetime.combine(
        tomorrow, datetime.time.min, tzinfo=PACIFIC
    )
    return midnight.astimezone(datetime.UTC)


def _usage_path(settings: Settings | None = None) -> Path:
    """Ruta del JSON de uso diario (junto a la carpeta de evidencia/data).

    Args:
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.

    Returns:
        Ruta del archivo ``api_usage.json``.
    """
    cfg = settings or get_settings()
    base = Path(cfg.evidence_dir).parent
    return base / "api_usage.json"


def _read_usage(settings: Settings | None = None) -> dict[str, dict[str, int]]:
    """Lee el mapa de uso persistido (``{}`` si no hay archivo o esta corrupto).

    Args:
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.

    Returns:
        Diccionario ``{provider: {date_iso: count}}``.
    """
    path = _usage_path(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("No se pudo leer api_usage (%s): %s", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    # Normaliza tipos (defensivo contra JSON manipulado a mano).
    result: dict[str, dict[str, int]] = {}
    for provider, by_date in data.items():
        if not isinstance(by_date, dict):
            continue
        result[provider] = {
            str(d): int(c) for d, c in by_date.items() if isinstance(c, (int, float))
        }
    return result


def daily_limit(provider: str, settings: Settings | None = None) -> int:
    """Resuelve el limite diario configurable de un provider cloud.

    Lee ``ocr_<provider>_daily_limit`` de `Settings` (env var
    ``OCR_<PROVIDER>_DAILY_LIMIT``). Default CONSERVADOR (`ocr_default_daily_limit`,
    200) si no esta definido para ese provider.

    Args:
        provider: Nombre del provider cloud (gemini/glm/azure/google).
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.

    Returns:
        Limite diario de requests (entero positivo).
    """
    cfg = settings or get_settings()
    specific = getattr(cfg, f"ocr_{provider}_daily_limit", None)
    if isinstance(specific, int) and specific > 0:
        return specific
    return cfg.ocr_default_daily_limit


def usage_today(
    provider: str,
    *,
    settings: Settings | None = None,
    now: datetime.datetime | None = None,
) -> int:
    """Cuenta las llamadas reales hechas hoy (Pacific) a un provider.

    Args:
        provider: Nombre del provider cloud.
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.
        now: Instante de referencia (para tests). Si es ``None`` usa el actual.

    Returns:
        Numero de requests del provider en el dia Pacific actual (0 si ninguna).
    """
    today = pacific_today(now).isoformat()
    by_date = _read_usage(settings).get(provider, {})
    return int(by_date.get(today, 0))


def record_usage(
    provider: str,
    *,
    settings: Settings | None = None,
    now: datetime.datetime | None = None,
) -> int:
    """Incrementa (atomico) el contador del dia para un provider cloud.

    Se llama UNA vez por request real a un provider cloud. Los providers locales
    no deben llamar a esto (no consumen cuota externa). Persiste en disco.

    Args:
        provider: Nombre del provider cloud (gemini/glm/azure/google).
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.
        now: Instante de referencia (para tests). Si es ``None`` usa el actual.

    Returns:
        El nuevo contador del dia tras incrementar.
    """
    cfg = settings or get_settings()
    today = pacific_today(now).isoformat()
    path = _usage_path(cfg)

    with _LOCK:
        usage = _read_usage(cfg)
        by_date = usage.setdefault(provider, {})
        new_count = int(by_date.get(today, 0)) + 1
        by_date[today] = new_count

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    limit = daily_limit(provider, cfg)
    if new_count >= limit:
        logger.warning(
            "Cuota diaria de '%s' ALCANZADA: %d/%d (Pacific %s). Provider no-usable hoy.",
            provider, new_count, limit, today,
        )
    elif new_count >= int(limit * WARN_THRESHOLD):
        logger.warning(
            "Cuota diaria de '%s' al %d%%: %d/%d (Pacific %s).",
            provider, round(new_count / limit * 100), new_count, limit, today,
        )
    return new_count


def is_over_limit(
    provider: str,
    *,
    settings: Settings | None = None,
    now: datetime.datetime | None = None,
) -> bool:
    """Indica si el provider ya alcanzo su limite diario (no-usable hoy).

    Solo aplica a providers cloud; los locales nunca se frenan por cuota.

    Args:
        provider: Nombre del provider.
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.
        now: Instante de referencia (para tests). Si es ``None`` usa el actual.

    Returns:
        ``True`` si el provider es cloud y su contador del dia alcanzo el limite.
    """
    if provider not in CLOUD_PROVIDERS:
        return False
    cfg = settings or get_settings()
    limit = daily_limit(provider, cfg)
    # Un límite <= 0 (misconfig) NO debe frenar permanentemente al provider
    # (`0 >= 0` daría True). Coherente con `usage_for`, que protege con limit > 0.
    if limit <= 0:
        return False
    return usage_today(provider, settings=cfg, now=now) >= limit


def over_limit_reason(
    provider: str,
    *,
    settings: Settings | None = None,
    now: datetime.datetime | None = None,
) -> str:
    """Mensaje legible del motivo de freno por cuota (para logs/estado).

    Args:
        provider: Nombre del provider.
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.
        now: Instante de referencia. Si es ``None`` usa el actual.

    Returns:
        Texto explicando el limite alcanzado y cuando se resetea.
    """
    cfg = settings or get_settings()
    used = usage_today(provider, settings=cfg, now=now)
    limit = daily_limit(provider, cfg)
    return (
        f"Cuota diaria gratis alcanzada: {used}/{limit} requests hoy. "
        "Se resetea a medianoche (太平洋時間) — mientras tanto cae al fallback local."
    )


def usage_for(
    provider: str,
    *,
    settings: Settings | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Arma el payload de uso de un provider cloud (para el endpoint/UI).

    Args:
        provider: Nombre del provider cloud.
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.
        now: Instante de referencia. Si es ``None`` usa el actual.

    Returns:
        Diccionario con ``provider``, ``used_today``, ``daily_limit``,
        ``percent`` (0-100, redondeado), ``over_limit``, ``warn`` (>=80%) y
        ``resets_at`` (ISO UTC del proximo reseteo Pacific).
    """
    cfg = settings or get_settings()
    used = usage_today(provider, settings=cfg, now=now)
    limit = daily_limit(provider, cfg)
    percent = round(used / limit * 100) if limit > 0 else 0
    return {
        "provider": provider,
        "used_today": used,
        "daily_limit": limit,
        "percent": percent,
        "over_limit": used >= limit,
        "warn": used >= int(limit * WARN_THRESHOLD) and used < limit,
        "resets_at": next_reset_at(now).isoformat(),
    }


def usage_report(
    *,
    settings: Settings | None = None,
    now: datetime.datetime | None = None,
) -> list[dict[str, Any]]:
    """Reporte de uso de TODOS los providers cloud (para ``GET /ocr/usage``).

    Args:
        settings: Settings a usar. Si es ``None`` usa `get_settings()`.
        now: Instante de referencia. Si es ``None`` usa el actual.

    Returns:
        Lista de payloads `usage_for` (uno por provider cloud).
    """
    cfg = settings or get_settings()
    return [usage_for(p, settings=cfg, now=now) for p in CLOUD_PROVIDERS]
