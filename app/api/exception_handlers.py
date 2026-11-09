"""Convierte los errores en respuestas HTTP claras."""

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
    """Resume los campos que fallaron en una validación.

    Args:
        exc: Error que se está manejando.

    Returns:
        El texto con los errores encontrados.
    """
    failures = [
        f"{'.'.join(str(part) for part in failure['loc'])}: {failure['msg']}"
        for failure in exc.errors()
    ]
    return "Request validation failed on " + "; ".join(failures)


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """Devuelve un error del servicio con su estado HTTP.

    Args:
        request: Petición HTTP recibida.
        exc: Error que se está manejando.

    Returns:
        La respuesta JSON del error.
    """
    return problem_response(exc, instance=request.url.path)


async def validation_error_handler(
    request: Request, exc: RequestValidationError | PydanticValidationError
) -> JSONResponse:
    """Convierte un error de validación en un 400.

    Args:
        request: Petición HTTP recibida.
        exc: Error que se está manejando.

    Returns:
        La respuesta JSON del error.
    """
    logger.info("request validation failed on %s", request.url.path)
    return problem_response(ValidationError(_describe(exc)), instance=request.url.path)


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Traduce los errores HTTP de FastAPI al formato del servicio.

    Args:
        request: Petición HTTP recibida.
        exc: Error que se está manejando.

    Returns:
        La respuesta JSON del error.
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
    """Registra un error inesperado y devuelve un 500.

    Args:
        request: Petición HTTP recibida.
        exc: Error que se está manejando.

    Returns:
        La respuesta JSON del error.
    """
    logger.exception("unhandled exception on %s", request.url.path, exc_info=exc)
    return problem_response(InternalError(), instance=request.url.path)


def register_exception_handlers(app: FastAPI) -> None:
    """Registra los manejadores de errores en la aplicación.

    Args:
        app: Aplicación FastAPI.

    Returns:
        No retorna valor.
    """
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)
