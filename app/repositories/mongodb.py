"""Capa 3: cliente de MongoDB y operaciones del ciclo de vida.

SPEC §6.1 usa `pymongo.AsyncMongoClient`, la API asíncrona oficial.
Este módulo traduce las excepciones del driver a errores de dominio de
`app/errors.py` y nunca al revés: el acceso a datos no conoce códigos HTTP
(SPEC §6.4).

Las operaciones de índice (`index_specs`, `IndexSpec`, las constantes de
índice y `ttl_index`) viven en `app/repositories/index_specs.py`; este módulo
las re-exporta para no romper imports existentes.
"""

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
    """Abrir el cliente con el timeout del despliegue.

    `AsyncMongoClient` no conecta en el constructor: conectar es trabajo de la
    primera operación. Por eso abrir no puede fallar y el `ping` de §6.5 paso 3
    es un paso aparte y no un adorno.
    """
    return AsyncMongoClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=settings.mongo_timeout_ms,
    )


def audit_logs_collection(
    client: AsyncMongoClient[Document], settings: Settings
) -> Any:
    """La colección de `audit_logs` en la base configurada.

    Se resuelve siempre por configuración y nunca por defecto: escribir en la
    base equivocada no da error, deja datos donde nadie los busca.
    """
    return client.get_database(settings.mongo_database).get_collection(
        settings.mongo_audit_logs_collection
    )


async def ping(client: AsyncMongoClient[Document]) -> None:
    """Comprobar que Mongo responde, traduciendo el fallo al dominio.

    SPEC §6.5 paso 3. El `detail` es fijo a propósito: el texto del driver suele
    traer `host:port` y con él parte de la URI, que acaba en logs ajenos al
    servicio.

    Raises:
        AuditStorageError: Si el driver falla al responder.
    """
    try:
        await client.admin.command("ping")
    except PyMongoError as exc:
        raise AuditStorageError(STORAGE_UNAVAILABLE) from exc


async def ensure_indexes(collection: Any, *, retention_days: int) -> None:
    """Crear los índices de §6.3, incluido el TTL si la retención está activa.

    Es idempotente: `create_indexes` no hace nada si el índice ya existe con las
    mismas opciones.

    Raises:
        AuditStorageError: Si el driver rechaza la creación.
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
