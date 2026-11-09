"""Define los índices que necesita la base de datos."""

from dataclasses import dataclass
from typing import Any

from pymongo import IndexModel

SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class IndexSpec:
    """Un índice de SPEC §6.3 declarado como dato.

    `descending` son los campos en orden descendente; el resto va ascendente.
    """

    name: str
    fields: tuple[str, ...]
    descending: frozenset[str] = frozenset()
    unique: bool = False
    expire_after_seconds: int | None = None

    @property
    def keys(self) -> list[tuple[str, int]]:
        """Devuelve los campos del índice con su orden."""
        return [(field, -1 if field in self.descending else 1) for field in self.fields]

    def to_index_model(self) -> IndexModel:
        """Convierte la definición en un modelo de índice de PyMongo."""
        options: dict[str, Any] = {"name": self.name, "unique": self.unique}
        if self.expire_after_seconds is not None:
            options["expireAfterSeconds"] = self.expire_after_seconds
        return IndexModel(self.keys, **options)


UNIQUE_IDEMPOTENCY_INDEX = IndexSpec(
    name="unq_audit_event_identity",
    fields=("action", "entity_type", "checksum", "performed_at"),
    unique=True,
)

CHECKSUM_LOOKUP_INDEX = IndexSpec(
    name="idx_checksum_performed",
    fields=("checksum", "performed_at", "_id"),
    descending=frozenset({"performed_at", "_id"}),
)

GLOBAL_LOOKUP_INDEX = IndexSpec(
    name="idx_performed",
    fields=("performed_at", "_id"),
    descending=frozenset({"performed_at", "_id"}),
)


def ttl_index(retention_days: int) -> IndexSpec | None:
    """Crea el índice de borrado automático si hay retención.

    Args:
        retention_days: Días que se conservan los registros.

    Returns:
        La definición del índice o None si está desactivada.
    """
    if retention_days <= 0:
        return None
    return IndexSpec(
        name="ttl_performed_at",
        fields=("performed_at",),
        expire_after_seconds=retention_days * SECONDS_PER_DAY,
    )


def index_specs(retention_days: int) -> tuple[IndexSpec, ...]:
    """Devuelve todos los índices que debe crear el servicio.

    Args:
        retention_days: Días que se conservan los registros.

    Returns:
        La lista ordenada de índices.
    """
    specs = [UNIQUE_IDEMPOTENCY_INDEX, CHECKSUM_LOOKUP_INDEX, GLOBAL_LOOKUP_INDEX]
    ttl = ttl_index(retention_days)
    if ttl is not None:
        specs.append(ttl)
    return tuple(specs)
