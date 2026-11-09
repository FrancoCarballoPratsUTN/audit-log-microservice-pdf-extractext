"""Prepara la respuesta al guardar una auditoría."""
from urllib.parse import quote

from fastapi import status
from fastapi.responses import JSONResponse

from app.api.schemas import AuditLogResponse
from app.services.audit_log_service import CreateResult

LOCATION_PREFIX = "/audit/logs/checksum/"


def present_create_result(result: CreateResult) -> JSONResponse:
    """Convierte el resultado del servicio en una respuesta HTTP.

    Args:
        result: Resultado del servicio.

    Returns:
        La respuesta con el código y las cabeceras adecuadas.
    """
    headers = {"Location": LOCATION_PREFIX + quote(result.log.checksum, safe="")}
    if result.replay:
        headers["X-Idempotent-Replay"] = "true"
    body = AuditLogResponse.from_log(result.log, replay=result.replay)
    return JSONResponse(
        status_code=status.HTTP_200_OK if result.replay else status.HTTP_201_CREATED,
        content=body.model_dump(by_alias=True),
        headers=headers,
    )
