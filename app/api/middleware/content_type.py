"""Exige que las peticiones POST usen JSON."""

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
        """Exige que el POST use el tipo JSON.

        Args:
            request: Petición HTTP recibida.
            call_next: Siguiente capa que procesa la petición.

        Returns:
            La respuesta o un error 415.
        """
        if request.method == "POST":
            media_type = request.headers.get(CONTENT_TYPE_HEADER, "")
            declared = media_type.split(";", 1)[0].strip().lower()
            if declared != JSON_MEDIA_TYPE:
                return problem_response(
                    UnsupportedMediaTypeError(), instance=request.url.path
                )
        return await call_next(request)
