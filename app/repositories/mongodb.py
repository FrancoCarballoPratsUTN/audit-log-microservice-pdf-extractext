"""Abre la conexión y prepara la base de datos."""

import logging
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.config import Settings
from app.errors import AuditStorageError
from app.repositories.index_specs import (
    CHECKSUM_LOOKUP_INDEX as CHECKSUM_LOOKUP_INDEX,
)
from app.repositories.index_specs import (
    GLOBAL_LOOKUP_INDEX as GLOBAL_LOOKUP_INDEX,
)
from app.repositories.index_specs import (
    UNIQUE_IDEMPOTENCY_INDEX as UNIQUE_IDEMPOTENCY_INDEX,
)
from app.repositories.index_specs import (
    index_specs as index_specs,
)
from app.repositories.index_specs import (
    ttl_index as ttl_index,
)

logger = logging.getLogger(__name__)

STORAGE_UNAVAILABLE = "MongoDB is unavailable."

Document = dict[str, Any]


def open_client(settings: Settings) -> AsyncMongoClient[Document]:
    """Crea el cliente de MongoDB con el tiempo de espera configurado.

    Args:
        settings: Configuración del servicio.

    Returns:
        El cliente de MongoDB.
    """
    return AsyncMongoClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=settings.mongo_timeout_ms,
    )


def audit_logs_collection(
    client: AsyncMongoClient[Document], settings: Settings
) -> Any:
    """Obtiene la colección de auditorías configurada.

    Args:
        client: Cliente que usa la prueba.
        settings: Configuración del servicio.

    Returns:
        La colección de MongoDB.
    """
    return client.get_database(settings.mongo_database).get_collection(
        settings.mongo_audit_logs_collection
    )


async def ping(client: AsyncMongoClient[Document]) -> None:
    """Comprueba que MongoDB responde.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        No retorna valor.

    Raises:
        AuditStorageError: Si MongoDB no responde.
    """
    try:
        await client.admin.command("ping")
    except PyMongoError as exc:
        raise AuditStorageError(STORAGE_UNAVAILABLE) from exc


async def ensure_indexes(collection: Any, *, retention_days: int) -> None:
    """Crea los índices necesarios en la colección.

    Args:
        collection: Colección de MongoDB.
        retention_days: Días que se conservan los registros.

    Returns:
        No retorna valor.

    Raises:
        AuditStorageError: Si los índices no se pueden crear.
    """
    specs = index_specs(retention_days)
    models = [spec.to_index_model() for spec in specs]
    try:
        await collection.create_indexes(models)
    except PyMongoError as exc:
        raise AuditStorageError("MongoDB indexes could not be created.") from exc
    logger.info(
        "indexes verified: %s",
        ", ".join(spec.name for spec in specs),
    )
