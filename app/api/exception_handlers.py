"""Exception handlers: donde un fallo se convierte en una respuesta HTTP.

La Capa 1 es la única que puede saber de códigos de estado, y este módulo es
donde vive ese conocimiento. Tres responsabilidades, por orden de importancia:

1. `RequestValidationError` se convierte en `400 VALIDATION_ERROR`. El `422` de
   FastAPI no satisface al cliente de Go: `ParseProblem` rellena un `Problem{}`
   con todos sus miembros a cero, el orquestador llama a `WriteHeader(0)` y su
   servidor HTTP hace panic (SPEC §2.6). Ningún camino de este módulo emite `422`.
2. `ServiceError` conserva el estado, las cabeceras y el código que declara.
3. Cualquier otra cosa se convierte en `500` sin detalle: una excepción no
   prevista que llega al cliente como texto es una fuga.

`StarletteHTTPException` no necesita que se inspeccione su causa: el enrutado
responde 404 y 405, y `str(exc)` es la frase del propio framework sobre la
petición, así que el cliente sigue aprendiendo qué estaba mal en *su* llamada.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.problem import problem_response
from app.errors import (
    InternalError,
    MethodNotAllowedError,
    NotFoundError,
    ServiceError,
    ValidationError,
)

logger = logging.getLogger(__name__)

HTTP_ERRORS: dict[int, type[ServiceError]] = {
    404: NotFoundError,
    405: MethodNotAllowedError,
}


def _describe(exc: PydanticValidationError) -> str:
    """Una frase que nombra qué falló, y nada sobre el valor enviado.

    Pydantic reporta la entrada problemática en `input` e internos del validador
    en `ctx` y `url`; los tres se descartan, porque el valor puede ser un secreto
    y el resto apunta dentro de la pila de validación (SPEC §7.1).
    """
    failures = [
        f"{'.'.join(str(part) for part in failure['loc'])}: {failure['msg']}"
        for failure in exc.errors()
    ]
    return "Request validation failed on " + "; ".join(failures)


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """Reportar un error de dominio con el estado que declara."""
    return problem_response(exc, instance=request.url.path)


async def validation_error_handler(
    request: Request, exc: RequestValidationError | PydanticValidationError
) -> JSONResponse:
    """Responder `400 VALIDATION_ERROR` en vez del `422` de FastAPI (SPEC §3.3 D1)."""
    logger.info("request validation failed on %s", request.url.path)
    return problem_response(ValidationError(_describe(exc)), instance=request.url.path)


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Traducir los 404 y 405 del propio framework a la matriz de errores.

    Cualquier otro estado se convierte en un 500 genérico a propósito: la matriz
    de SPEC §7.2 tiene ocho filas, e inventar un noveno código aquí haría
    divergir el contrato.
    """
    error_class = HTTP_ERRORS.get(exc.status_code)
    if error_class is None:
        logger.warning(
            "excepción HTTP inesperada %s en %s", exc.status_code, request.url.path
        )
        return problem_response(InternalError(), instance=request.url.path)

    return problem_response(error_class(str(exc.detail)), instance=request.url.path)


async def unexpected_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Último recurso: `500` con detalle genérico, causa sólo en el log."""
    logger.exception("unhandled exception on %s", request.url.path, exc_info=exc)
    return problem_response(InternalError(), instance=request.url.path)


def register_exception_handlers(app: FastAPI) -> None:
    """Enganchar los handlers a `app`. Se invoca una vez, desde la fábrica."""
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(PydanticValidationError, validation_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)
