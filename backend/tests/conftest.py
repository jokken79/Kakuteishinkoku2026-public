"""Fixtures compartidas de pytest para los tests del dominio.

Usa SQLite en memoria (StaticPool) creando el schema con
`Base.metadata.create_all`, de modo que los tests no necesitan PostgreSQL ni
Alembic corriendo.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import create_db_engine, get_session_factory
from app.models import Base


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    """Engine SQLite en memoria con el schema creado.

    Yields:
        Engine con todas las tablas del dominio creadas.
    """
    eng = create_db_engine("sqlite://")
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    """Sesion de SQLAlchemy ligada al engine de test.

    Yields:
        Sesion lista para usar; se cierra al finalizar el test.
    """
    factory = get_session_factory(engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
