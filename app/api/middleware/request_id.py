"""Añade un identificador único a cada petición."""
import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Añade un identificador único a cada petición.

        Args:
            request: Petición HTTP recibida.
            call_next: Siguiente capa que procesa la petición.

        Returns:
            La respuesta con el identificador incluido.
        """
        inbound_request_id = request.headers.get(REQUEST_ID_HEADER, "").strip()
        if REQUEST_ID_PATTERN.fullmatch(inbound_request_id):
            request_id = inbound_request_id
        else:
            request_id = uuid.uuid4().hex
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
