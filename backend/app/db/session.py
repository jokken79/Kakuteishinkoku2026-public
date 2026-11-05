"""Engine y fabrica de sesiones de SQLAlchemy.

Crea el engine a partir de `Settings.database_url`. Soporta PostgreSQL
(produccion) y SQLite (dev/test). Para SQLite aplica los pragmas/argumentos
necesarios (`check_same_thread=False`, `StaticPool` para bases en memoria) de
modo que la misma conexion se comparta entre threads de los tests.

`get_db` es un generador pensado para usarse como dependencia de FastAPI (lo
montaran los routers de otra fase).
"""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def create_db_engine(database_url: str | None = None) -> Engine:
    """Crea un engine de SQLAlchemy para la URL dada.

    Args:
        database_url: URL de conexion. Si es ``None`` usa la de `Settings`.

    Returns:
        Engine configurado segun el dialecto (SQLite vs PostgreSQL).
    """
    url = database_url or get_settings().database_url
    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {"future": True, "pool_pre_ping": True}

    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        # Para SQLite en memoria, StaticPool mantiene una unica conexion viva
        # de modo que todas las sesiones vean el mismo schema y datos.
        if ":memory:" in url or url.endswith("sqlite://"):
            engine_kwargs["poolclass"] = StaticPool
        engine_kwargs.pop("pool_pre_ping", None)

    logger.info("Creando engine para %s", url.split("@")[-1])
    return create_engine(url, connect_args=connect_args, **engine_kwargs)


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Devuelve una fabrica de sesiones ligada a un engine.

    Args:
        engine: Engine a usar. Si es ``None`` usa el engine por defecto.

    Returns:
        `sessionmaker` configurada (sin autoflush implicito agresivo).
    """
    return sessionmaker(
        bind=engine or get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )


# Engine por defecto (perezoso): se crea la primera vez que se pide.
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Devuelve el engine por defecto (singleton perezoso).

    Returns:
        Engine creado a partir de `Settings.database_url`.
    """
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def SessionLocal() -> Session:  # noqa: N802 (nombre convencional tipo fabrica)
    """Crea una nueva sesion ligada al engine por defecto.

    Returns:
        Sesion de SQLAlchemy lista para usar.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory(get_engine())
    return _session_factory()


def get_db() -> Generator[Session, None, None]:
    """Dependencia de FastAPI: provee una sesion y la cierra al terminar.

    Yields:
        Sesion de SQLAlchemy con scope de request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
