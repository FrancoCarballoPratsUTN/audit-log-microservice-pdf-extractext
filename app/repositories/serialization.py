"""Convierte entre registros y documentos de MongoDB."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from bson import ObjectId

from app.domain.models import AuditLog, CreateAuditLogRequest


def to_document(
    request: CreateAuditLogRequest, *, received_at: datetime
) -> dict[str, Any]:
    """Convierte una petición en un documento de MongoDB.

    Args:
        request: Petición HTTP recibida.
        received_at: Fecha y hora en que se recibió el evento.

    Returns:
        El documento listo para guardar.
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
    """Convierte un documento de MongoDB en un registro.

    Args:
        document: Documento de MongoDB.

    Returns:
        El registro de auditoría.
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
