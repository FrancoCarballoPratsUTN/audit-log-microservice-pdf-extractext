"""Capa 1: el endpoint `POST /audit/logs`.

Cierra el camino vertical de escritura (SPEC §4.4): valida el cuerpo con
Pydantic, comprueba el límite de `details` **antes** de tocar la Capa 2, pide el
servicio por dependency injection y responde `201` con el registro y su
`Location`, o `200` con las dos señales de replay (`X-Idempotent-Replay` y el
campo `idempotent_replay`) cuando el evento ya estaba almacenado (SPEC §7.4).

El `Location` escapa el checksum con `quote(..., safe="")`: el checksum es un
string opaco (SPEC §5.2) que puede llevar `/`, `?`, comillas o `#`, y un
`Location` sin escapar con un `/` extra no apuntaría al recurso correcto.

Este módulo no conoce `pymongo` ni `app.repositories`: pedir el servicio y
traducir su resultado es lo único que le corresponde a la Capa 1. `tests/unit/
test_package_layout.py` lo fija por código fuente.
"""

import json
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.api.dependencies import get_audit_log_service
from app.api.schemas import AuditEventRequest, AuditLogResponse
from app.domain.models import CreateAuditLogRequest
from app.errors import PayloadTooLargeError
from app.services.audit_log_service import AuditLogService

router = APIRouter(tags=["audit"])

LOCATION_PREFIX = "/audit/logs/checksum/"


@router.post(
    "/audit/logs",
    response_model=AuditLogResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {
            "model": AuditLogResponse,
            "description": "El evento ya estaba almacenado (replay, §7.4).",
        },
        400: {"description": "Cuerpo inválido: clave desconocida, fecha sin offset."},
        401: {"description": "Credenciales ausentes o inválidas."},
        413: {"description": "El campo 'details' excede MAX_DETAILS_BYTES."},
        415: {"description": "Content-Type distinto de application/json."},
    },
)
async def create_audit_log(
    request: Request,
    event: AuditEventRequest,
    service: AuditLogService = Depends(get_audit_log_service),
) -> JSONResponse:
    """Guardar un evento de auditoría, o informar de un replay idempotente.

    Args:
        request: Petición en curso; porta la configuración en `app.state`.
        event: Cuerpo ya validado por Pydantic.
        service: El caso de uso, inyectado por `app.state`.

    Returns:
        `201` + `Location` + el registro completo, o `200` + señales de replay.

    Raises:
        PayloadTooLargeError: Si `details` serializado supera el límite del
            despliegue. Se lanza antes de llamar al servicio: nada se escribe.
    """
    details: Any = {} if event.details is None else event.details
    settings = request.app.state.settings

    if len(json.dumps(details)) > settings.max_details_bytes:
        raise PayloadTooLargeError()

    result = await service.create(
        CreateAuditLogRequest(
            action=event.action,
            entity_type=event.entity_type,
            checksum=event.checksum,
            performed_at=event.performed_at,
            details=details,
        )
    )

    headers = {"Location": LOCATION_PREFIX + quote(result.log.checksum, safe="")}
    if result.replay:
        headers["X-Idempotent-Replay"] = "true"

    body = AuditLogResponse.from_log(result.log, replay=result.replay)
    return JSONResponse(
        status_code=status.HTTP_200_OK if result.replay else status.HTTP_201_CREATED,
        content=body.model_dump(by_alias=True),
        headers=headers,
    )


__all__ = ["router"]
