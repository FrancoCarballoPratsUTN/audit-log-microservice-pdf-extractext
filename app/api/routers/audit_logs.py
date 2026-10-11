"""Capa 1: los endpoints de `/audit/logs`.

El `POST` cierra el camino vertical de escritura (SPEC §4.4): valida el cuerpo
con Pydantic, comprueba el límite de `details` **antes** de tocar la Capa 2, pide
el servicio por dependency injection y responde `201` con el registro y su
`Location`, o `200` con las dos señales de replay (`X-Idempotent-Replay` y el
campo `idempotent_replay`) cuando el evento ya estaba almacenado (SPEC §7.4).

El `GET` cierra la lectura global (SPEC §8.1): la respuesta es un **array de
primer nivel** —`{"logs": […]}` haría fallar el `json.Decode` del cliente Go y
el orquestador respondería `502` aunque este servicio funcionara bien (SPEC
§2.5 H1)— y el rango de `skip`/`limit` se rechaza con `400` antes de llegar a
la Capa 2: un recorte silencioso haría creer al cliente que su página está
completa (D16).

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

from fastapi import APIRouter, Depends, Request, Security, status
from fastapi.responses import JSONResponse

from app.api.auth import bearer_scheme
from app.api.dependencies import get_audit_log_service
from app.api.schemas import (
    AuditEventRequest,
    AuditLogItem,
    AuditLogResponse,
    ProblemDetails,
)
from app.domain.models import CreateAuditLogRequest
from app.errors import PayloadTooLargeError, ValidationError
from app.services.audit_log_service import AuditLogService

# `Security(bearer_scheme)` no autoriza nada —eso lo hace el middleware—: publica
# el requisito `Bearer` en cada operación para que /docs dibuje el candado.
# El `4XX` documenta el cuerpo de todos los errores de la matriz a la vez y, de
# paso, impide que FastAPI inyecte el `422` que este servicio nunca emite
# (SPEC §2.6): la comprobación en `fastapi.openapi.utils` sólo lo añade si no hay
# ya un `4XX`.
ERROR_RESPONSES = {
    "4XX": {
        "model": ProblemDetails,
        "description": "Error de la matriz de SPEC §7.2 como problem details "
        "(`application/problem+json`, RFC 9457).",
    }
}

router = APIRouter(
    tags=["audit"],
    dependencies=[Security(bearer_scheme)],
)

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
        **ERROR_RESPONSES,
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


@router.get(
    "/audit/logs",
    response_model=list[AuditLogItem],
    summary="Listar eventos ordenados por performed_at descendente",
    responses={
        400: {
            "description": "'skip' o 'limit' fuera de rango (§5.2): se "
            "rechazan, nunca se recortan."
        },
        401: {"description": "Credenciales ausentes o inválidas."},
        **ERROR_RESPONSES,
    },
)
async def list_audit_logs(
    request: Request,
    skip: int = 0,
    limit: int | None = None,
    service: AuditLogService = Depends(get_audit_log_service),
) -> list[AuditLogItem]:
    """Listar eventos con paginación, en `performed_at desc, _id desc` (§8.1).

    Args:
        request: Petición en curso; porta la configuración en `app.state`.
        skip: Elementos a omitir; 0 si se omite.
        limit: Tamaño de página; `DEFAULT_LIMIT` del despliegue si se omite.
        service: El caso de uso, inyectado por `app.state`.

    Returns:
        Un **array de primer nivel** con los 7 campos de `models.AuditLog` por
        elemento; `[]` si no hay resultados, nunca un `404` (SPEC §4.5).

    Raises:
        ValidationError: Si `skip` queda fuera de `[0, MAX_SKIP]` o `limit`
            fuera de `[1, MAX_LIMIT]`. El rango se rechaza en la Capa 1
            (SPEC §3.2) y **antes** de llamar al servicio: un recorte
            silencioso haría creer al cliente que su página está completa.
    """
    settings = request.app.state.settings
    page_limit = settings.default_limit if limit is None else limit

    if not 0 <= skip <= settings.max_skip:
        raise ValidationError(f"skip must be between 0 and {settings.max_skip}.")
    if not 1 <= page_limit <= settings.max_limit:
        raise ValidationError(f"limit must be between 1 and {settings.max_limit}.")

    logs = await service.list_page(skip=skip, limit=page_limit)
    return [AuditLogItem.from_log(log) for log in logs]


@router.get(
    "/audit/logs/checksum/{checksum}",
    response_model=list[AuditLogItem],
    summary="Listar eventos de un checksum",
    responses={
        401: {"description": "Credenciales ausentes o inválidas."},
        **ERROR_RESPONSES,
    },
)
async def list_audit_logs_by_checksum(
    checksum: str,
    service: AuditLogService = Depends(get_audit_log_service),
) -> list[AuditLogItem]:
    """Listar los eventos de un checksum, con el orden del contrato (§8.1).

    El path es exactamente `/audit/logs/checksum/{valor}` (`client_test.go:156`)
    y el checksum es un string **opaco** (SPEC §5.2): llega tal cual al filtro,
    sin normalizar. Sin paginación: el cliente Go no la envía (D12), y recortar
    en silencio haría creer que la lista está completa.

    Args:
        checksum: El checksum del path, ya desescapado por el framework.
        service: El caso de uso, inyectado por `app.state`.

    Returns:
        Un **array de primer nivel** con los 7 campos de `models.AuditLog` por
        elemento; `[]` si no hay coincidencias, nunca un `404`
        (`client_test.go:170`).
    """
    logs = await service.list_by_checksum(checksum)
    return [AuditLogItem.from_log(log) for log in logs]


__all__ = ["router"]
