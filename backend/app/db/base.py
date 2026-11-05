"""Base declarativa de SQLAlchemy 2.0.

Define la `Base` (clase declarativa) y los mixins/tipos comunes que comparten
todos los modelos del dominio. Importar `Base` desde aqui garantiza que toda la
metadata quede registrada en un unico `MetaData`, que Alembic usa como
`target_metadata` para autogenerar migraciones.

Convencion de montos: enteros (yenes). Nunca usar Float/Numeric para dinero.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Convencion de nombres para constraints/indices: hace que Alembic genere
# nombres deterministas (necesario para migraciones reproducibles en SQLite).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Clase base declarativa para todos los modelos del dominio."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Mixin con columnas de auditoria temporal.

    Args:
        created_at: Instante de creacion (UTC, set por la BD).
        updated_at: Instante de ultima modificacion (UTC, set por la BD).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
