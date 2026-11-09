"""Define los datos principales de una auditoría."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _ensure_utc(value: datetime) -> datetime:
    """Convierte una fecha a UTC con zona horaria.

    Args:
        value: Valor que se va a revisar.

    Returns:
        La fecha en UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_millis(value: datetime) -> datetime:
    """Convierte a UTC y recorta a milisegundos.

    Args:
        value: Valor que se va a revisar.

    Returns:
        La fecha normalizada a milisegundos.
    """
    utc = _ensure_utc(value)
    return utc.replace(microsecond=(utc.microsecond // 1000) * 1000)


def _normalize_details(details: Any) -> Any:
    """Convierte los detalles ausentes en un diccionario vacío.

    Args:
        details: Datos adicionales del evento.

    Returns:
        Los detalles normalizados.
    """
    return {} if details is None else details


def _normalize_domain_instance(instance: object, **fields: object) -> None:
    """Aplica las funciones de normalización a una instancia.

    Args:
        instance: Ruta de la petición que produjo el error.
        **fields: Argumentos adicionales.

    Returns:
        No retorna valor.
    """
    for name, func in fields.items():
        object.__setattr__(instance, name, func(getattr(instance, name)))


def rfc3339_utc(value: datetime) -> str:
    """Formatea una fecha en UTC con milisegundos.

    Args:
        value: Valor que se va a revisar.

    Returns:
        La fecha como texto RFC 3339.
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
        """Normaliza la fecha y los detalles al crear la petición."""
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
        """Normaliza las fechas y los detalles del registro."""
        _normalize_domain_instance(
            self,
            performed_at=_to_millis,
            received_at=_to_millis,
            details=_normalize_details,
        )


def to_wire_fields(log: AuditLog) -> dict[str, Any]:
    """Devuelve los siete campos que se envían al cliente.

    Args:
        log: Registro de auditoría.

    Returns:
        Un diccionario con los campos del registro.
    """
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
