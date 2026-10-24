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
import os
import signal
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI

from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import install_middleware
from app.api.routers.audit_logs import router as audit_logs_router
from app.api.routers.health import router as health_router
from app.config import Settings, get_settings, get_settings_from_values
from app.consul import load_prefix
from app.consul_agent import deregister_service, register_service
from app.errors import AuditStorageError
from app.repositories.mongo_audit_log_repository import MongoAuditLogRepository
from app.repositories.mongodb import (
    audit_logs_collection,
    ensure_indexes,
    open_client,
    ping,
)
from app.services.audit_log_service import AuditLogService

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger(__name__)


def _settings_from_environment_or_consul() -> Settings:
    if os.getenv("CONSUL_ENABLED", "").lower() != "true":
        return get_settings()
    values = load_prefix(
        os.getenv("CONSUL_HTTP_ADDR", ""),
        os.getenv("CONSUL_HTTP_TOKEN", ""),
        os.getenv("CONSUL_KV_PREFIX", ""),
        ca_file=os.getenv("CONSUL_HTTP_CA_FILE"),
    )
    return get_settings_from_values(values)


def _consul_registration() -> dict[str, object] | None:
    if os.getenv("CONSUL_ENABLED", "").lower() != "true":
        return None
    address = os.getenv("CONSUL_SERVICE_ADDRESS") or socket.gethostname()
    port = int(os.getenv("CONSUL_SERVICE_PORT", os.getenv("PORT", "8000")))
    service_name = os.getenv("CONSUL_SERVICE_NAME", "auditlog")
    service_id = os.getenv("CONSUL_SERVICE_ID") or f"{service_name}-{address}"
    tags_env = os.getenv("CONSUL_SERVICE_TAGS", "")
    # Aceptar ';' o ',' como separador. Los tags permiten pasar labels/middlewares
    # y patrones de routing al registro de Consul.
    tags: list[str] = []
    for part in tags_env.replace(",", ";").split(";"):
        tag = part.strip()
        if tag:
            tags.append(tag)
    return {
        "address": os.getenv("CONSUL_HTTP_ADDR", ""),
        "token": os.getenv("CONSUL_HTTP_TOKEN", ""),
        "ca_file": os.getenv("CONSUL_HTTP_CA_FILE"),
        "service_id": service_id,
        "service_name": service_name,
        "service_address": address,
        "service_port": port,
        "check_url": os.getenv(
            "CONSUL_SERVICE_CHECK_URL",
            f"http://{address}:{port}/readyz",
        ),
        "tags": tags,
    }


def _install_deregister_handler(
    deregister: Callable[[], None],
) -> Callable[[], None]:
    """Deregistrar al recibir SIGTERM/SIGINT, antes de que uvicorn drene."""
    previous_handlers: dict[int, Any] = {}

    def handle_signal(signum: int, frame: Any) -> None:
        deregister()
        previous = previous_handlers.get(signum)
        if callable(previous):
            previous(signum, frame)

    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(ValueError, AttributeError):
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, handle_signal)

    def restore() -> None:
        for sig, previous in previous_handlers.items():
            with suppress(ValueError, AttributeError):
                signal.signal(sig, previous)

    return restore


def _configure_logging() -> None:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _setup_signal_handlers() -> None:
    def _handle_sig(signum, _frame) -> None:
        sig_name = "UNKNOWN"
        signals_cls = getattr(signal, "Signals", None)
        if signals_cls is not None:
            with suppress(Exception):
                sig_name = signals_cls(signum).name
        logger.info("shutdown signal received: %s (%s)", sig_name, signum)

    with suppress(ValueError, AttributeError):
        signal.signal(signal.SIGTERM, _handle_sig)
    with suppress(ValueError, AttributeError):
        signal.signal(signal.SIGINT, _handle_sig)


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

    # El servicio y el repositorio, construidos una vez en el arranque y
    # guardados en `app.state`: el router los pide por dependency injection y
    # ningún test tiene que saber cómo se montan (SPEC §12).
    app.state.audit_log_service = AuditLogService(
        MongoAuditLogRepository(audit_logs_collection(client, settings))
    )
    registration = _consul_registration()
    if registration is not None:
        register_service(**registration)

    deregistered = False

    def deregister() -> None:
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

    restore_signal_handlers = (
        _install_deregister_handler(deregister)
        if registration is not None
        else lambda: None
    )

    try:
        try:
            await ping(client)
            await ensure_indexes(
                audit_logs_collection(client, settings),
                retention_days=settings.retention_days,
            )
        except AuditStorageError as exc:
            logger.warning("startup without a ready MongoDB: %s", exc.detail)
        logger.info("application startup complete")
        yield
    finally:
        restore_signal_handlers()
        deregister()
        logger.info("application shutdown initiated: closing MongoDB client")
        await client.close()
        logger.info("application shutdown complete")


def create_app() -> FastAPI:
    """Construir la aplicación.

    Returns:
        Una app lista con sus handlers, middleware y routers registrados.

    Raises:
        ValidationError: Si `SERVICE_API_TOKEN` falta o está en blanco. El
            servicio no arranca en ese caso, a propósito (SPEC §3.6).
    """
    _configure_logging()
    _setup_signal_handlers()

    settings = _settings_from_environment_or_consul()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)

    # El stack de middleware se monta en un solo sitio, `install_middleware`, con
    # la autenticación *outermost*: su `401` tiene que responder antes del
    # enrutado, antes del `415` y antes del `413` (SPEC §4.3).
    install_middleware(app, max_body_bytes=settings.max_body_bytes)

    app.include_router(health_router)
    app.include_router(audit_logs_router)
    app.state.settings = settings
    app.state.api_token = settings.service_api_token.get_secret_value()
    return app
