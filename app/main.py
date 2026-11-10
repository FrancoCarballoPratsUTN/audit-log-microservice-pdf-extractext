"""Crea la aplicación y controla su arranque y cierre."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import install_middleware
from app.api.routers.audit_logs import router as audit_logs_router
from app.api.routers.health import router as health_router
from app.config import Settings, load_settings
from app.services.consul.consul_agent import consul_registration, deregister_service, register_service
from app.errors import AuditStorageError
from app.logging import configure_logging
from app.repositories.mongo_audit_log_repository import MongoAuditLogRepository
from app.repositories.mongodb import audit_logs_collection, open_client
from app.repositories.readiness import ReadinessProbe
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepara MongoDB y Consul al arrancar y los cierra al salir.

    Args:
        app: Aplicación FastAPI.

    Returns:
        No retorna valor.
    """
    settings: Settings = app.state.settings
    client = open_client(settings)
    app.state.mongo_client = client

    collection = audit_logs_collection(client, settings)
    app.state.audit_log_service = AuditLogService(MongoAuditLogRepository(collection))
    app.state.readiness_probe = ReadinessProbe(
        client, collection, retention_days=settings.retention_days
    )
    app.state.active_requests = 0

    registration = consul_registration()
    if registration is not None:
        register_service(**registration)

    deregistered = False

    def deregister() -> None:
        """Quita el servicio de Consul una sola vez."""
        nonlocal deregistered
        if deregistered or registration is None:
            return
        try:
            deregister_service(
                registration["address"],
                registration["token"],
                registration["service_id"],
                ca_file=registration["ca_file"],
            )
        except Exception:
            logger.exception("Consul service deregistration failed.")
        else:
            deregistered = True

    try:
        try:
            await app.state.readiness_probe()
        except AuditStorageError as exc:
            logger.warning("startup without a ready MongoDB: %s", exc.detail)
        logger.info("application startup complete")
        yield
    finally:
        deregister()
        while app.state.active_requests > 0:
            await asyncio.sleep(0.1)
        logger.info("application shutdown initiated: closing MongoDB client")
        await client.close()
        logger.info("application shutdown complete")


def create_app() -> FastAPI:
    """Construye y configura la aplicación FastAPI."""
    settings = load_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    install_middleware(app, max_body_bytes=settings.max_body_bytes)

    app.include_router(health_router)
    app.include_router(audit_logs_router)
    app.state.settings = settings
    app.state.api_token = settings.service_api_token.get_secret_value()
    app.state.active_requests = 0
    return app


if __name__ == "__main__":
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=8083,
    )
