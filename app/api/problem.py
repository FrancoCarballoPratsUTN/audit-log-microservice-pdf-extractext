"""Cuerpos problem details de RFC 9457.

El único sitio donde un error de dominio se convierte en bytes sobre el cable. El
cliente de Go parsea todo cuerpo con `status >= 300` esperando `type`, `title`,
`status` y `detail` (SPEC §2.6), así que un error que salga de este servicio de
otra forma le cuesta un `502` al orquestador.

Aquí no se toca ningún logger: la causa concreta de un fallo pertenece al log de
quien lo capturó, nunca a la respuesta.
"""

from typing import Any

from fastapi.responses import JSONResponse

from app.api.schemas import ProblemDetails
from app.errors import ServiceError

PROBLEM_MEDIA_TYPE = "application/problem+json"


def build_problem(error: ServiceError, *, instance: str) -> ProblemDetails:
    """Rellenar un cuerpo de problema a partir de un error de dominio.

    `detail` explica *esta* ocurrencia y viene del error; `title` se mantiene
    genérico para que dos ocurrencias del mismo problema comparen iguales
    (SPEC §7.1).

    Args:
        error: El error de dominio que se reporta.
        instance: Path de la petición, sin host y sin valores de query.

    Returns:
        El cuerpo a serializar.
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
    """Serializar un error de dominio como `application/problem+json`.

    Args:
        error: El error de dominio que se reporta.
        instance: Path de la petición, sin host y sin valores de query.

    Returns:
        Una respuesta con el código de estado propio del error y las cabeceras
        que éste exige.
    """
    body: dict[str, Any] = build_problem(error, instance=instance).model_dump()
    return JSONResponse(
        status_code=error.status,
        content=body,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=error.headers,
    )
