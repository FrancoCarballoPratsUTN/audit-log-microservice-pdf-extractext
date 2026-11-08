"""Montar el stack de middlewares en el orden del contrato.

`add_middleware` **antepone**, así que se añaden del más interno al más
externo: `BearerAuthMiddleware` queda *outermost* y su `401` precede al `415`
y al `413`; el `400` de la validación llega después, tras el enrutado.
"""

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.auth import BearerAuthMiddleware
from app.api.middleware.access_log import AccessLogMiddleware
from app.api.middleware.body_size import BodySizeLimitMiddleware
from app.api.middleware.content_type import ContentTypeMiddleware
from app.api.middleware.request_id import RequestIdMiddleware

CORS_METHODS = ["GET", "POST", "OPTIONS"]


def install_middleware(app: FastAPI, *, max_body_bytes: int) -> None:
    """Enganchar los middlewares en el orden del contrato (SPEC §4.3)."""
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
