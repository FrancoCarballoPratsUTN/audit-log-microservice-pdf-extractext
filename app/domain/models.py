"""Modelo de dominio.

Separamos el contrato del dominio del esquema HTTP (Capa 1) y del documento Mongo
(Capa 3). Esto cumple con las 3 capas con dependencia hacia adentro y evita que
las capas superiores conozcan detalles de PyMongo (SPEC §12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _ensure_utc(value: datetime) -> datetime:
    """Garantiza que las fechas sean UTC-aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CreateAuditLogRequest:
    """Datos entrantes para crear un registro de auditoría.

    Args:
        action: Acción realizada (p.ej. `pdf.extract`, `text.delete`).
        entity_type: Tipo de entidad afectada.
        checksum: Suma de verificación del contenido (aceptado tal cual).
        performed_at: Momento en que ocurrió la acción (ISO 8601 UTC).
        details: Datos extra. Si no se indica, es `{}`.
    """

    action: str
    entity_type: str
    checksum: str
    performed_at: datetime
    details: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Usamos object.__setattr__ porque el dataclass es frozen
        object.__setattr__(self, "performed_at", _ensure_utc(self.performed_at))


@dataclass(frozen=True, slots=True)
class AuditLog:
    """Registro de auditoría ya persistido.

    Args:
        id: Identificador interno del registro (valor del repositorio).
        action: Acción realizada.
        entity_type: Tipo de entidad afectada.
        checksum: Suma de verificación.
        performed_at: Momento en que ocurrió la acción (UTC).
        received_at: Momento en que el servicio recibió la petición (UTC).
        details: Datos extra. Siempre presente.
    """

    id: str
    action: str
    entity_type: str
    checksum: str
    performed_at: datetime
    received_at: datetime
    details: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Usamos object.__setattr__ porque el dataclass es frozen
        object.__setattr__(self, "performed_at", _ensure_utc(self.performed_at))
        object.__setattr__(self, "received_at", _ensure_utc(self.received_at))
        if self.details is None:
            object.__setattr__(self, "details", {})


__all__ = ["AuditLog", "CreateAuditLogRequest"]
