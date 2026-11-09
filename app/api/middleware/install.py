"""Instala los middlewares en el orden correcto."""

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.auth import BearerAuthMiddleware
from app.api.middleware.access_log import AccessLogMiddleware
from app.api.middleware.body_size import BodySizeLimitMiddleware
from app.api.middleware.content_type import ContentTypeMiddleware
from app.api.middleware.request_id import RequestIdMiddleware

CORS_METHODS = ["GET", "POST", "OPTIONS"]


def install_middleware(app: FastAPI, *, max_body_bytes: int) -> None:
    """Instala los middlewares en el orden correcto.

    Args:
        app: Aplicación FastAPI.
        max_body_bytes: Tamaño máximo del cuerpo.

    Returns:
        No retorna valor.
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
