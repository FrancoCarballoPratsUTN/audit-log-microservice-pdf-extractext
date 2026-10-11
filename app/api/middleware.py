"""Middlewares de transporte: orden único, forma de la respuesta y observabilidad.

`install_middleware` es el único sitio que resuelve el orden del *stack*. La
fábrica (`app.main`) y los tests de comportamiento lo llaman, así que lo que se
prueba es el orden real y no una copia que puede divergir.

El orden, de fuera hacia dentro, es:

    BearerAuth (401) → RequestId → ContentType (415) → BodySize (413) → CORS → log

- La autenticación va primero (SPEC §4.3): no se parsea ni se limita el body de
  quien no se ha identificado.
- `RequestIdMiddleware` corre **por fuera** de los límites a propósito, para que
  un `415`, un `413` y hasta el `400` de Pydantic viajen con su `X-Request-ID` y
  se puedan correlacionar en el log. Es la única razón de que no esté después.
- `ContentType` precede a `BodySize`: un `text/plain` de 2 MiB es `415`, no `413`
  (AC de T14). Y ninguna de las dos lee el cuerpo: la primera mira la cabecera
  `Content-Type` y la segunda `Content-Length`.
- `CORS` queda por **dentro** de la autenticación: un preflight a una ruta
  protegida sigue siendo `401`. El cliente es un proceso Go que no navega; CORS
  existe para no cerrar la puerta a un consumidor de navegador sobre las rutas
  abiertas, no para abrir las protegidas.
- El log de acceso es el más interno: registra método, ruta, estado y duración de
  lo que llegó a ejecutarse.

Ninguno de estos middlewares conoce Mongo ni el servicio: son forma del
transporte, no reglas de negocio (SPEC §3.1).
"""

import logging
import time
import uuid

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.auth import BearerAuthMiddleware
from app.api.problem import problem_response
from app.errors import PayloadTooLargeError, UnsupportedMediaTypeError

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
CONTENT_TYPE_HEADER = "Content-Type"
CONTENT_LENGTH_HEADER = "Content-Length"
JSON_MEDIA_TYPE = "application/json"
CORS_METHODS = ["GET", "POST", "OPTIONS"]


def parse_content_length(value: str | None) -> int:
    """Interpretar `Content-Length` sin confiar en él.

    Un valor ausente o no numérico cuenta como `0` en vez de reventar: el límite
    de body no debe convertirse en un `500` por una cabecera malformada de un
    llamador (AC de T14). Un valor negativo tampoco tiene sentido como tamaño y
    también cuenta como `0`.

    Args:
        value: El valor crudo de la cabecera, o `None` si no vino.

    Returns:
        El tamaño declarado, nunca negativo; `0` si no es interpretable.
    """
    if value is None:
        return 0
    try:
        length = int(value)
    except ValueError:
        return 0
    return max(length, 0)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Eco de `X-Request-ID`, generándolo si el llamador no lo envía.

    El identificador se deja en `request.state.request_id` para que el log de
    acceso y cualquier capa interna lo reutilicen sin volver a mirar la cabecera.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Resolver el identificador, seguir la cadena y devolverlo en la respuesta."""
        inbound = request.headers.get(REQUEST_ID_HEADER)
        request_id = (
            inbound.strip() if inbound and inbound.strip() else uuid.uuid4().hex
        )
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class ContentTypeMiddleware(BaseHTTPMiddleware):
    """Exigir `application/json` en el `POST` (SPEC §4.4 paso 3).

    Sólo el `POST` lleva cuerpo en este contrato, así que sólo el `POST` exige
    media type. La comparación ignora parámetros (`; charset=utf-8`) y
    mayúsculas: el media type es *case-insensitive* según RFC 9110 §8.3.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Responder `415` a un `POST` que no declare JSON, o continuar."""
        if request.method == "POST":
            media_type = request.headers.get(CONTENT_TYPE_HEADER, "")
            declared = media_type.split(";", 1)[0].strip().lower()
            if declared != JSON_MEDIA_TYPE:
                return problem_response(
                    UnsupportedMediaTypeError(), instance=request.url.path
                )
        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rechazar con `413` un cuerpo cuya `Content-Length` supere el límite.

    Decide **sólo** con la cabecera: no lee el cuerpo, así que una subida enorme
    se rechaza antes de entrar en memoria (AC de T14). Es el mismo principio del
    `401`: el trabajo caro no se hace para una petición que va a fallar.
    """

    def __init__(self, app: object, *, max_bytes: int) -> None:
        """Guardar el límite del despliegue.

        Args:
            app: La aplicación ASGI que envuelve.
            max_bytes: Tamaño máximo aceptado del body, en bytes.
        """
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Responder `413` si la `Content-Length` declarada excede el límite."""
        if parse_content_length(request.headers.get(CONTENT_LENGTH_HEADER)) > (
            self._max_bytes
        ):
            return problem_response(PayloadTooLargeError(), instance=request.url.path)
        return await call_next(request)


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Registrar una línea por petición servida, con su duración.

    El identificador de petición viaja en la línea para poder cruzar el acceso
    con los logs de auth y del servicio. Una excepción no capturada se registra
    antes de dejarla subir: quien la convierte en `500` es el handler de último
    recurso, no este middleware.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Medir, registrar y devolver; registrar también si algo revienta."""
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "access %s %s -> 500 in %.1f ms",
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "access %s %s -> %s in %.1f ms (request_id=%s)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            getattr(request.state, "request_id", "-"),
        )
        return response


def install_middleware(app: FastAPI, *, max_body_bytes: int) -> None:
    """Montar el stack de middlewares en el orden del contrato (SPEC §4.3).

    `add_middleware` **antepone**, así que se añaden del más interno al más
    externo: el último añadido (`BearerAuthMiddleware`) queda *outermost* y su
    `401` precede al `415` y al `413`.

    Args:
        app: La aplicación a la que enganchar los middlewares.
        max_body_bytes: Límite de body del despliegue (`MAX_BODY_BYTES`).

    Notes:
        CORS se abre a `*` porque el SPEC no define orígenes configurables
        (§3.6) y el servicio es interno y está protegido por token; no se
        permiten credenciales de navegador, así que el comodín no amplía lo que
        un origen ajeno puede hacer.
    """
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=CORS_METHODS,
        allow_headers=["*"],
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_body_bytes)
    app.add_middleware(ContentTypeMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(BearerAuthMiddleware)


__all__ = [
    "AccessLogMiddleware",
    "BodySizeLimitMiddleware",
    "ContentTypeMiddleware",
    "RequestIdMiddleware",
    "install_middleware",
    "parse_content_length",
]
