"""X-Request-ID`, generándolo si falta o no es seguro."""

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
        """Resolver el identificador, seguir la cadena y devolverlo en la respuesta."""
        inbound_request_id = request.headers.get(REQUEST_ID_HEADER, "").strip()
        if REQUEST_ID_PATTERN.fullmatch(inbound_request_id):
            request_id = inbound_request_id
        else:
            request_id = uuid.uuid4().hex
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
