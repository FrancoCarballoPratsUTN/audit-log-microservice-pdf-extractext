"""Mapeo BSON ⇄ dominio.

`to_document` construye el documento de escritura y `to_audit_log` lo convierte
de vuelta al dominio. El formato de los siete campos del cable vive en
`app.domain.models.to_wire_fields`.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from bson import ObjectId

from app.domain.models import AuditLog, CreateAuditLogRequest


def to_document(
    request: CreateAuditLogRequest, *, received_at: datetime
) -> dict[str, Any]:
    """El documento de §6.2 que Mongo debe guardar.

    Args:
        request: Datos del evento ya normalizados por el dominio, sin `id` ni
            `received_at`.
        received_at: Instante (UTC) en que el servidor recibió la petición;
            BSON `Date` lo guarda con precisión de milisegundos.

    Returns:
        El documento con `_id` nuevo y `details` nunca `null`.
    """
    return {
        "_id": ObjectId(),
        "action": request.action,
        "entity_type": request.entity_type,
        "checksum": request.checksum,
        "details": request.details,
        "performed_at": request.performed_at,
        "received_at": received_at,
    }


def to_audit_log(document: Mapping[str, Any]) -> AuditLog:
    """El registro de dominio que el repositorio devuelve y la capa de
    servicios consume.

    PyMongo devuelve fechas *naive* interpretadas en UTC; `AuditLog` las
    normaliza a UTC-aware y las trunca a milisegundos en su `__post_init__`.

    Args:
        document: Documento leído de Mongo.

    Returns:
        El registro con `id` en hex y fechas UTC con precisión de ms.
    """
    return AuditLog(
        id=str(document["_id"]),
        action=document["action"],
        entity_type=document["entity_type"],
        checksum=document["checksum"],
        performed_at=document["performed_at"],
        received_at=document["received_at"],
        details=document.get("details"),
    )


__all__ = ["to_audit_log", "to_document"]
