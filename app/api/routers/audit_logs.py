"""Rutas para crear y consultar registros de auditoría."""

from fastapi import APIRouter, Depends, Request, Security, status
from fastapi.responses import JSONResponse

from app.api.auth import bearer_scheme
from app.api.dependencies import get_audit_log_service
from app.api.presenters.audit_log import present_create_result
from app.api.schemas import (
    AuditEventRequest,
    AuditLogItem,
    AuditLogResponse,
    ProblemDetails,
)
from app.api.validators.details import validate_details
from app.domain.models import CreateAuditLogRequest
from app.errors import ValidationError
from app.services.audit_log_service import AuditLogService

ERROR_RESPONSES = {
    "4XX": {
        "model": ProblemDetails,
        "description": "Error de la matriz de SPEC §7.2 (RFC 9457).",
    }
}

router = APIRouter(
    tags=["audit"],
    dependencies=[Security(bearer_scheme)],
)


@router.post(
    "/audit/logs",
    response_model=AuditLogResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": AuditLogResponse, "description": "Replay idempotente (§7.4)."},
        400: {"description": "Cuerpo inválido."},
        401: {"description": "Token faltante o inválido."},
        413: {"description": "'details' excede el límite."},
        415: {"description": "Content-Type no es application/json."},
        **ERROR_RESPONSES,
    },
)
async def create_audit_log(
    request: Request,
    event: AuditEventRequest,
    service: AuditLogService = Depends(get_audit_log_service),
) -> JSONResponse:
    """Recibe un evento y lo guarda en la auditoría.

    Args:
        request: Petición HTTP recibida.
        event: Datos del evento.
        service: Servicio de auditoría.

    Returns:
        La respuesta HTTP con el evento guardado.
    """
    audit_log = CreateAuditLogRequest(
        action=event.action,
        entity_type=event.entity_type,
        checksum=event.checksum,
        performed_at=event.performed_at,
        details=event.details,
    )
    settings = request.app.state.settings
    validate_details(event.details, settings.max_details_bytes)

    result = await service.create(audit_log)
    return present_create_result(result)


@router.get(
    "/audit/logs",
    response_model=list[AuditLogItem],
    responses={
        400: {"description": "'skip'/'limit' fuera de rango."},
        **ERROR_RESPONSES,
    },
)
async def list_audit_logs(
    request: Request,
    skip: int = 0,
    limit: int | None = None,
    service: AuditLogService = Depends(get_audit_log_service),
) -> list[AuditLogItem]:
    """Devuelve una página de registros de auditoría.

    Args:
        request: Petición HTTP recibida.
        skip: Cantidad de resultados que se van a omitir.
        limit: Cantidad máxima de resultados.
        service: Servicio de auditoría.

    Returns:
        La lista de registros.
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
    responses={**ERROR_RESPONSES},
)
async def list_audit_logs_by_checksum(
    checksum: str,
    service: AuditLogService = Depends(get_audit_log_service),
) -> list[AuditLogItem]:
    """Devuelve los registros de un checksum.

    Args:
        checksum: Valor que identifica el contenido.
        service: Servicio de auditoría.

    Returns:
        La lista de registros.
    """
    logs = await service.list_by_checksum(checksum)
    return [AuditLogItem.from_log(log) for log in logs]
