"""Capa de acceso a datos: Base declarativa, engine y sesiones.

Exporta los componentes de SQLAlchemy 2.0 que el resto del backend usa para
persistir el dominio. Soporta SQLite (dev/test) y PostgreSQL (config via
`Settings.database_url`). Todos los montos del dominio se almacenan en enteros
(yenes, sin decimales).
"""

from app.db.base import Base
from app.db.session import (
    SessionLocal,
    create_db_engine,
    get_db,
    get_engine,
    get_session_factory,
)

__all__ = [
    "Base",
    "SessionLocal",
    "create_db_engine",
    "get_db",
    "get_engine",
    "get_session_factory",
]
