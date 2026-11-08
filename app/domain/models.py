"""Modelo de dominio.

Separamos el contrato del dominio del esquema HTTP (Capa 1) y del documento Mongo
(Capa 3). Esto cumple con las 3 capas con dependencia hacia adentro y evita que
las capas superiores conozcan detalles de PyMongo (SPEC §12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _ensure_utc(value: datetime) -> datetime:
    """Garantiza que las fechas sean UTC-aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_millis(value: datetime) -> datetime:
    """Normaliza a UTC y trunca los microsegundos a milisegundos.

    La identidad y la deduplicación usan granularidad de 1 ms. Se trunca, no se
    redondea: `.123456` y `.123000` producen la misma identidad.
    """
    utc = _ensure_utc(value)
    return utc.replace(microsecond=(utc.microsecond // 1000) * 1000)


def _normalize_details(details: Any) -> Any:
    """`details` ausente es `{}`; cualquier otro valor se conserva."""
    return {} if details is None else details


def _normalize_domain_instance(instance: object, **fields: object) -> None:
    """Normalizar campos de una instancia de dominio frozen.

    El dataclass es `frozen`, así que se usa `object.__setattr__`. Cada campo se
    normaliza con la función pasada (p. ej. `_to_millis` o `_normalize_details`).
    """
    for name, func in fields.items():
        object.__setattr__(instance, name, func(getattr(instance, name)))


def rfc3339_utc(value: datetime) -> str:
    """RFC 3339 en UTC con `Z` y milisegundos, truncando los microsegundos.

    Es la representación que parsea `time.Time` del orquestador (§2.4).
    """
    utc = value.astimezone(UTC)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


@dataclass(frozen=True, slots=True)
class CreateAuditLogRequest:
    """Datos entrantes para crear un registro de auditoría."""

    action: str
    entity_type: str
    checksum: str
    performed_at: datetime
    details: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalize_domain_instance(
            self, performed_at=_to_millis, details=_normalize_details
        )


@dataclass(frozen=True, slots=True)
class AuditLog:
    """Registro de auditoría ya persistido."""

    id: str
    action: str
    entity_type: str
    checksum: str
    performed_at: datetime
    received_at: datetime
    details: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalize_domain_instance(
            self,
            performed_at=_to_millis,
            received_at=_to_millis,
            details=_normalize_details,
        )


def to_wire_fields(log: AuditLog) -> dict[str, Any]:
    """Los siete campos que comparten la escritura y la lectura."""
    return {
        "_id": log.id,
        "action": log.action,
        "entity_type": log.entity_type,
        "checksum": log.checksum,
        "details": log.details,
        "performed_at": rfc3339_utc(log.performed_at),
        "received_at": rfc3339_utc(log.received_at),
    }


__all__ = ["AuditLog", "CreateAuditLogRequest", "rfc3339_utc", "to_wire_fields"]
