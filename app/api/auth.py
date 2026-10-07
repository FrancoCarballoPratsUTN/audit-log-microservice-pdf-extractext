"""Autenticación por token Bearer.

Cuatro maneras de fallar, una sola respuesta. El `detail` es idéntico para una
cabecera ausente, un valor vacío, un esquema ajeno y un valor incorrecto, a
propósito: distinguirlos le daría a un atacante un oráculo para adivinar
credenciales (SPEC §4.2).

Es una preocupación de transporte, así que vive entera en la Capa 1.
`AuditLogService` nunca llega a saber que existe un token.

La autenticación se ejecuta antes del enrutado: un sondeo sin credenciales
recibe `401` también para un path que no existe, de modo que la superficie de la
API no se puede mapear desde fuera.
"""

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.problem import problem_response
from app.errors import UnauthorizedError

logger = logging.getLogger(__name__)

SCHEME = "Bearer"
PUBLIC_PATHS = frozenset({"/health", "/readyz"})

REASON_MISSING = "missing header"
REASON_EMPTY = "empty credential"
REASON_SCHEME = "unexpected scheme"
REASON_MISMATCH = "credential does not match"


def extract_bearer(authorization: str | None) -> tuple[str | None, str]:
    """Separar la cabecera `Authorization` en credencial y motivo de rechazo.

    Args:
        authorization: Valor crudo de la cabecera.

    Returns:
        La credencial, o `None` si la cabecera no es utilizable, más el motivo
        del rechazo, que va al log y nunca al cliente.
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
    """Decidir si una petición puede continuar.

    Args:
        authorization: Valor crudo de la cabecera `Authorization`.
        token: La credencial esperada.

    Returns:
        True sólo si el esquema es `Bearer` y la credencial coincide.
    """
    credential, reason = extract_bearer(authorization)
    if credential is None:
        logger.info("rejected request: %s", reason)
        return False
    if not credential.strip():
        logger.info("rejected request: %s", REASON_EMPTY)
        return False
    if not secrets.compare_digest(credential, token):
        logger.info("rejected request: %s", REASON_MISMATCH)
        return False
    return True


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Rechazar toda petición que no lleve la credencial compartida.

    La credencial se lee de `app.state.api_token`, donde el composition root la
    dejó una vez al arrancar. El middleware queda sin estado: no hay subclase por
    app ni token capturado en un closure.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Autenticar la petición, o responder `401`."""
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        token: str = request.app.state.api_token
        if is_authorized(request.headers.get("Authorization"), token):
            return await call_next(request)

        return problem_response(UnauthorizedError(), instance=request.url.path)
