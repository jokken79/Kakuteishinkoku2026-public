"""Tipos de columna portables entre SQLite (dev/test) y PostgreSQL (prod).

- `GUID`: usa `UUID` nativo en PostgreSQL y `CHAR(36)` en el resto.
- `PortableJSON`: usa `JSONB` en PostgreSQL y el tipo `JSON` generico en SQLite.

Esto permite que los modelos declaren `Mapped[uuid.UUID]` / `Mapped[dict]` sin
acoplarse a un dialecto concreto.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CHAR
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import JSON, TypeDecorator


class GUID(TypeDecorator[uuid.UUID]):
    """UUID portable.

    Usa el tipo `UUID` de PostgreSQL cuando esta disponible y `CHAR(36)` en
    otros dialectos (SQLite). Almacena/lee siempre `uuid.UUID` en Python.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        """Selecciona la implementacion segun el dialecto."""
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Any) -> str | uuid.UUID | None:
        """Convierte el valor Python al formato de la BD."""
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        """Convierte el valor de la BD a `uuid.UUID`."""
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class PortableJSON(TypeDecorator[Any]):
    """JSON portable: `JSONB` en PostgreSQL, `JSON` generico en SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        """Selecciona JSONB en PostgreSQL, JSON generico en el resto."""
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


def new_uuid() -> uuid.UUID:
    """Genera un nuevo UUID4.

    Returns:
        Un `uuid.UUID` aleatorio (version 4).
    """
    return uuid.uuid4()
