"""Ayudas comunes para probar los middlewares."""

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from app.api.auth import BearerAuthMiddleware
from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    ContentTypeMiddleware,
    RequestIdMiddleware,
    install_middleware,
)
from app.config import Settings
from app.main import create_app

TOKEN = "s3cr3t-shared-token"
LIMIT = 64
AUTH = {"Authorization": f"Bearer {TOKEN}"}
JSON = {"Content-Type": "application/json"}

EXPECTED_ORDER = [
    BearerAuthMiddleware,
    RequestIdMiddleware,
    ContentTypeMiddleware,
    BodySizeLimitMiddleware,
    CORSMiddleware,
    AccessLogMiddleware,
]


class Payload(BaseModel):
    """Cuerpo mínimo: obliga a FastAPI a parsear el body, para poder observar el
    `400` que queda *después* de `415` y `413`."""

    action: str = "pdf.extract"


def build_app(*, max_body_bytes: int = LIMIT) -> FastAPI:
    """App mínima con el stack real, sin Mongo: el rechazo ocurre antes de la ruta, así
    que no hace falta el servicio.

    Args:
        max_body_bytes: Tamaño máximo del cuerpo.

    Returns:
        La aplicación de prueba.
    """
    app = FastAPI()
    register_exception_handlers(app)
    app.state.api_token = TOKEN
    install_middleware(app, max_body_bytes=max_body_bytes)

    @app.post("/audit/logs", status_code=201)
    async def create(payload: Payload) -> dict[str, str]:
        """Crea una ruta que recibe un evento.

        Args:
            payload: Datos que se van a enviar.

        Returns:
            El resultado creado.
        """
        return {"action": payload.action}

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Crea una ruta de salud."""
        return {"status": "ok"}

    @app.get("/boom")
    async def boom() -> None:
        """Crea una ruta que lanza un error inesperado."""
        raise RuntimeError("boom")

    return app


__all__ = [
    "AUTH",
    "EXPECTED_ORDER",
    "JSON",
    "LIMIT",
    "Payload",
    "TOKEN",
    "build_app",
    "create_app",
    "Settings",
]
