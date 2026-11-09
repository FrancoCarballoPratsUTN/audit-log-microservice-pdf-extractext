"""Crea respuestas de error con el formato estándar."""

from typing import Any

from fastapi.responses import JSONResponse

from app.api.schemas import ProblemDetails
from app.errors import ServiceError

PROBLEM_MEDIA_TYPE = "application/problem+json"


def build_problem(error: ServiceError, *, instance: str) -> ProblemDetails:
    """Crea el cuerpo de error con el formato estándar.

    Args:
        error: Error que se va a lanzar o comprobar.
        instance: Ruta de la petición que produjo el error.

    Returns:
        Los datos del error listos para enviar.
    """
    return ProblemDetails(
        type=error.type_uri,
        title=error.title,
        status=error.status,
        detail=error.detail,
        instance=instance,
        code=error.code,
    )


def problem_response(error: ServiceError, *, instance: str) -> JSONResponse:
    """Convierte un error en una respuesta JSON.

    Args:
        error: Error que se va a lanzar o comprobar.
        instance: Ruta de la petición que produjo el error.

    Returns:
        La respuesta HTTP con el error.
    """
    body: dict[str, Any] = build_problem(error, instance=instance).model_dump()
    return JSONResponse(
        status_code=error.status,
        content=body,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=error.headers,
    )
