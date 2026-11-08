"""Rechazar con `413` un cuerpo sin tamaño declarado o por encima del límite.

Decide **sólo** con la cabecera `Content-Length`: no lee el cuerpo, así que una
subida enorme se rechaza antes de entrar en memoria.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.problem import problem_response
from app.errors import PayloadTooLargeError

CONTENT_LENGTH_HEADER = "Content-Length"


def parse_content_length(value: str | None) -> int:
    """Interpretar `Content-Length` sin confiar en él; nunca negativo."""
    if value is None:
        return 0
    try:
        length = int(value)
    except ValueError:
        return 0
    return max(length, 0)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Responder `413` si un `POST` no declara tamaño o excede el límite."""
        content_length = request.headers.get(CONTENT_LENGTH_HEADER)
        if request.method == "POST" and (
            content_length is None
            or parse_content_length(content_length) > self._max_bytes
        ):
            return problem_response(PayloadTooLargeError(), instance=request.url.path)
        return await call_next(request)
