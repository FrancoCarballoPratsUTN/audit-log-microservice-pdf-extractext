"""Composition root: el único sitio que sabe que todas las capas existen.

`create_app` cablea configuración, handlers, middleware y routers, y nada más en
el servicio importa entre capas para hacerlo.

La configuración se resuelve aquí y no en el import del módulo, así que
`import app.main` funciona sin entorno y `uvicorn app.main:create_app --factory`
falla al arrancar con un error de configuración en vez de al importar con un
traceback.

El `lifespan` es la fase que toca la red (SPEC §6.5). Va después de la
configuración y antes de servir tráfico, que es la única forma de que el orden
importe: `add_middleware` no admite cambios después de arrancar, y la colección
sólo existe tras `connection.start()`.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import BearerAuthMiddleware
from app.api.exception_handlers import register_exception_handlers
from app.api.routers.health import router as health_router
from app.config import Settings, get_settings
from app.errors import AuditStorageError
from app.repositories.mongodb import (
    audit_logs_collection,
    ensure_indexes,
    open_client,
    ping,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Abrir Mongo y preparar los índices, sin impedir el arranque.

    SPEC §6.5: si Mongo no responde, la app **arranca igualmente** y es `/readyz`
    quien reporta `503`. Un proceso vivo que responde sondas es recuperable por el
    orquestador; un proceso muerto no lo es. Pero los índices sí son requisito para
    servir tráfico, así que un fallo ahí se registra como error de arranque.
    """
    settings: Settings = app.state.settings
    client = open_client(settings)
    app.state.mongo_client = client

    try:
        try:
            await ping(client)
            await ensure_indexes(
                audit_logs_collection(client, settings),
                retention_days=settings.retention_days,
            )
        except AuditStorageError as exc:
            logger.warning("startup without a ready MongoDB: %s", exc.detail)

        yield
    finally:
        await client.close()


def create_app() -> FastAPI:
    """Construir la aplicación.

    Returns:
        Una app lista con sus handlers, middleware y routers registrados.

    Raises:
        ValidationError: Si `SERVICE_API_TOKEN` falta o está en blanco. El
            servicio no arranca en ese caso, a propósito (SPEC §3.6).
    """
    settings = get_settings()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)

    # Registrarlo el último lo hace el más externo: la autenticación tiene que
    # responder antes del enrutado, antes del `415` y antes del `413`
    # (SPEC §4.3).
    app.add_middleware(BearerAuthMiddleware)

    app.include_router(health_router)
    app.state.settings = settings
    app.state.api_token = settings.service_api_token.get_secret_value()
    return app
