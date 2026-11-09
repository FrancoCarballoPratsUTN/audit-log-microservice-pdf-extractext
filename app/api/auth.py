"""Comprueba el token de acceso de cada petición."""

import logging
import secrets

from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.problem import problem_response
from app.errors import UnauthorizedError

logger = logging.getLogger(__name__)

SCHEME = "Bearer"
# Documentación: el candado `Bearer` que /docs necesita para enviar el token y
# el esquema de seguridad que `/openapi.json` publica.
bearer_scheme = HTTPBearer(auto_error=False, scheme_name=SCHEME)

PUBLIC_PATHS = frozenset({"/health", "/readyz", "/docs", "/openapi.json"})

REASON_MISSING = "missing header"
REASON_EMPTY = "empty credential"
REASON_SCHEME = "unexpected scheme"
REASON_MISMATCH = "credential does not match"


def extract_bearer(authorization: str | None) -> tuple[str | None, str]:
    """Separa la cabecera de autorización en esquema y credencial.

    Args:
        authorization: Cabecera de autorización.

    Returns:
        La credencial y el motivo de rechazo.
    """
    if authorization is None:
        return None, REASON_MISSING

    scheme, separator, credential = authorization.partition(" ")
    if not separator:
        return None, REASON_EMPTY
    if scheme.lower() != SCHEME.lower():
        return None, REASON_SCHEME

    return credential, ""


def is_authorized(authorization: str | None, token: str) -> bool:
    """Comprueba si la petición trae el token correcto.

    Args:
        authorization: Cabecera de autorización.
        token: Token de acceso.

    Returns:
        True si el token es válido; False en caso contrario.
    """
    credential, reason = extract_bearer(authorization)
    if credential is None:
        logger.info("rejected request: %s", reason)
        return False
    if not credential.strip():
        logger.info("rejected request: %s", REASON_EMPTY)
        return False
    # compare_digest no acepta str no ASCII; con bytes sigue siendo tiempo constante.
    if not secrets.compare_digest(credential.encode(), token.encode()):
        logger.info("rejected request: %s", REASON_MISMATCH)
        return False
    return True


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Rechazar toda petición que no lleve la credencial compartida.

    La credencial se lee de `app.state.api_token`, donde el composition root la
    dejó una vez al arrancar. El middleware queda sin estado: no hay subclase
    por app ni token capturado en un closure.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Permite la petición solo si trae un token válido.

        Args:
            request: Petición HTTP recibida.
            call_next: Siguiente capa que procesa la petición.

        Returns:
            La respuesta de la siguiente capa o un error 401.
        """
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        token: str = request.app.state.api_token
        if is_authorized(request.headers.get("Authorization"), token):
            return await call_next(request)

        return problem_response(UnauthorizedError(), instance=request.url.path)
