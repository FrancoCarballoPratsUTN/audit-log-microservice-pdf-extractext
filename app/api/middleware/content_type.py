"""Exigir `application/json` en el `POST`"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.problem import problem_response
from app.errors import UnsupportedMediaTypeError

CONTENT_TYPE_HEADER = "Content-Type"
JSON_MEDIA_TYPE = "application/json"


class ContentTypeMiddleware(BaseHTTPMiddleware):
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
