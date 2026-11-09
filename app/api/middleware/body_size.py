"""Rechaza peticiones con un cuerpo demasiado grande."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.problem import problem_response
from app.errors import PayloadTooLargeError

CONTENT_LENGTH_HEADER = "Content-Length"


def parse_content_length(value: str | None) -> int:
    """Lee el tamaño del cuerpo sin confiar en el valor.

    Args:
        value: Valor que se va a revisar.

    Returns:
        El tamaño como número entero, nunca negativo.
    """
    if value is None:
        return 0
    try:
        length = int(value)
    except ValueError:
        return 0
    return max(length, 0)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, max_bytes: int) -> None:
        """Guarda el tamaño máximo permitido para el cuerpo.

        Args:
            app: Aplicación FastAPI.
            max_bytes: Tamaño máximo permitido.

        Returns:
            No retorna valor.
        """
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Rechaza los cuerpos demasiado grandes o sin tamaño.

        Args:
            request: Petición HTTP recibida.
            call_next: Siguiente capa que procesa la petición.

        Returns:
            La respuesta o un error 413.
        """
        content_length = request.headers.get(CONTENT_LENGTH_HEADER)
        if request.method == "POST" and (
            content_length is None
            or parse_content_length(content_length) > self._max_bytes
        ):
            return problem_response(PayloadTooLargeError(), instance=request.url.path)
        return await call_next(request)
