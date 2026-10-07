"""Mapeo BSON ⇄ dominio ⇄ dict de la API.

SPEC §6.2 y §2.4: un documento de Mongo no es un JSON de la API. Este módulo
es el único lugar donde se cruzan esos dos mundos — `ObjectId` → hex de 24
caracteres, fechas → RFC 3339 UTC con `Z` —, porque si cada endpoint
serializara por su cuenta acabarían conviviendo formatos distintos que el
orquestador acepta a ratos.

También construye el documento de escritura (`to_document`): el único que debe
saber que el `_id` lo genera Mongo y que `details` nunca se guarda como
`null`.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from app.domain.models import AuditLog, CreateAuditLogRequest


def to_document(
    request: CreateAuditLogRequest, *, received_at: datetime
) -> dict[str, Any]:
    """El documento de §6.2 que Mongo debe guardar.

    Args:
        request: Datos del evento, sin `id` ni `received_at`.
        received_at: Instante (UTC) en que el servidor recibió la petición.

    Returns:
        El documento con `_id` nuevo y `details` nunca `null`.
    """
    return {
        "_id": ObjectId(),
        "action": request.action,
        "entity_type": request.entity_type,
        "checksum": request.checksum,
        "details": {} if request.details is None else request.details,
        "performed_at": request.performed_at,
        "received_at": received_at,
    }


def to_audit_log(document: Mapping[str, Any]) -> AuditLog:
    """El registro de dominio que el repositorio devuelve y la capa de
    servicios consume.

    PyMongo devuelve fechas *naive* interpretadas en UTC; `AuditLog` las
    normaliza a UTC-aware en su `__post_init__`.

    Args:
        document: Documento leído de Mongo.

    Returns:
        El registro con `id` en hex y fechas con zona horaria.
    """
    details = document.get("details")
    return AuditLog(
        id=str(document["_id"]),
        action=document["action"],
        entity_type=document["entity_type"],
        checksum=document["checksum"],
        performed_at=document["performed_at"],
        received_at=document["received_at"],
        details={} if details is None else details,
    )


def render(log: AuditLog) -> dict[str, Any]:
    """Los siete campos de `models.AuditLog` con el formato de SPEC §2.4.

    `_id` sale como string plano (el orquestador espera un `string`, no un
    subdocumento `{"$oid": ...}`) y las fechas como RFC 3339 UTC con `Z` y
    milisegundos, que es lo que parsea `time.Time`.
    """
    return {
        "_id": log.id,
        "action": log.action,
        "entity_type": log.entity_type,
        "checksum": log.checksum,
        "details": log.details,
        "performed_at": _rfc3339(log.performed_at),
        "received_at": _rfc3339(log.received_at),
    }


def _rfc3339(value: datetime) -> str:
    """RFC 3339 en UTC con `Z` y milisegundos, truncando los microsegundos."""
    utc = value.astimezone(UTC)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


__all__ = ["render", "to_audit_log", "to_document"]
