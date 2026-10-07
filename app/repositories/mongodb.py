"""Capa 3: cliente de MongoDB y bootstrap de índices.

SPEC §6.1 usa `pymongo.AsyncMongoClient`, la API asíncrona oficial; `motor` está
en modo mantenimiento y no se usa.

Los índices de §6.3 se declaran **como datos** (`IndexSpec`) y se traducen a
`IndexModel` sólo al crear. La razón es que un índice mal escrito no falla: el
servicio arranca, responde bien y sólo se nota semanas después, cuando una página
de `skip/limit` devuelve filas distintas entre dos llamadas idénticas. Declararlos
como datos permite afirmarlos en un test sin abrir una conexión.

Este módulo traduce las excepciones del driver a errores de dominio de
`app/errors.py` y nunca al revés: el acceso a datos no conoce códigos HTTP
(SPEC §6.4). El mapeo completo de §6.4 lo fija T8, cuando exista el camino de
escritura; aquí sólo hacen falta `ping` y la creación de índices, que son las dos
únicas operaciones del arranque.
"""

import logging
from dataclasses import dataclass
from typing import Any

from pymongo import AsyncMongoClient, IndexModel
from pymongo.errors import PyMongoError

from app.config import Settings
from app.errors import AuditStorageError

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 24 * 60 * 60

Document = dict[str, Any]


@dataclass(frozen=True, slots=True)
class IndexSpec:
    """Un índice de SPEC §6.3 declarado como dato.

    Attributes:
        name: Nombre estable del índice, el mismo que muestra `getIndexes()`.
        fields: Campos del índice **en orden**: el orden de la tupla es el orden
            del índice en Mongo.
        descending: Campos que van en orden descendente. El resto, ascendente.
        unique: Si el índice rechaza valores duplicados.
        expire_after_seconds: TTL en segundos, o `None` si el índice no expira.
    """

    name: str
    fields: tuple[str, ...]
    descending: frozenset[str] = frozenset()
    unique: bool = False
    expire_after_seconds: int | None = None

    @property
    def keys(self) -> list[tuple[str, int]]:
        """Los pares `(campo, 1|-1)` que entiende `IndexModel`."""
        return [(field, -1 if field in self.descending else 1) for field in self.fields]

    def to_index_model(self) -> IndexModel:
        """Traducir el dato a la clase del driver."""
        options: dict[str, Any] = {"name": self.name, "unique": self.unique}
        if self.expire_after_seconds is not None:
            options["expireAfterSeconds"] = self.expire_after_seconds
        return IndexModel(self.keys, **options)


#: SPEC §6.3 fila 2. La tupla completa, no sólo el `checksum`: un mismo checksum
#: genera varios eventos (`pdf.extract`, `text.create`, `text.update`, ...).
UNIQUE_IDEMPOTENCY_INDEX = IndexSpec(
    name="unq_audit_event_identity",
    fields=("action", "entity_type", "checksum", "performed_at"),
    unique=True,
)

#: SPEC §6.3 fila 3, para `GET /audit/logs/checksum/{checksum}`.
CHECKSUM_LOOKUP_INDEX = IndexSpec(
    name="idx_checksum_performed",
    fields=("checksum", "performed_at", "_id"),
    descending=frozenset({"performed_at", "_id"}),
)

#: SPEC §6.3 fila 4, para `GET /audit/logs` global.
GLOBAL_LOOKUP_INDEX = IndexSpec(
    name="idx_performed",
    fields=("performed_at", "_id"),
    descending=frozenset({"performed_at", "_id"}),
)


def ttl_index(retention_days: int) -> IndexSpec | None:
    """El índice TTL de §6.3, o `None` si la retención está desactivada.

    `RETENTION_DAYS = 0` significa "no borres nada", no "borra ya": un TTL de cero
    segundos vaciaría la auditoría entera poco después de arrancar.

    Args:
        retention_days: Días de retención configurados.

    Returns:
        La especificación del índice TTL, o `None` si no debe crearse.
    """
    if retention_days <= 0:
        return None
    return IndexSpec(
        name="ttl_performed_at",
        fields=("performed_at",),
        expire_after_seconds=retention_days * SECONDS_PER_DAY,
    )


def index_specs(retention_days: int) -> tuple[IndexSpec, ...]:
    """Los índices que este servicio crea, en el orden en que los crea.

    Args:
        retention_days: Días de retención; decide si el TTL entra o no.

    Returns:
        Tres índices, o cuatro si la retención está activa.
    """
    specs = [UNIQUE_IDEMPOTENCY_INDEX, CHECKSUM_LOOKUP_INDEX, GLOBAL_LOOKUP_INDEX]
    ttl = ttl_index(retention_days)
    if ttl is not None:
        specs.append(ttl)
    return tuple(specs)


def open_client(settings: Settings) -> AsyncMongoClient[Document]:
    """Abrir el cliente con el timeout del despliegue.

    `AsyncMongoClient` no conecta en el constructor: conectar es trabajo de la
    primera operación. Por eso abrir no puede fallar y el `ping` de §6.5 paso 3 es
    un paso aparte y no un adorno.

    Args:
        settings: Configuración del despliegue.

    Returns:
        Un cliente sin conexiones abiertas todavía.
    """
    return AsyncMongoClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=settings.mongo_timeout_ms,
    )


def audit_logs_collection(
    client: AsyncMongoClient[Document], settings: Settings
) -> Any:
    """La colección de `audit_logs` en la base configurada.

    Se resuelve siempre por configuración y nunca por defecto: escribir en la base
    equivocada no da error, deja datos donde nadie los busca.
    """
    return client.get_database(settings.mongo_database).get_collection(
        settings.mongo_audit_logs_collection
    )


async def ping(client: AsyncMongoClient[Document]) -> None:
    """Comprobar que Mongo responde, traduciendo el fallo al dominio.

    SPEC §6.5 paso 3. El `detail` es fijo a propósito: el texto del driver suele
    traer `host:port` y con él parte de la URI, que acaba en logs ajenos al
    servicio.

    Args:
        client: Cliente abierto.

    Raises:
        AuditStorageError: Si el driver falla al responder. La Capa 1 lo traduce
            a `503`, que sí es reintentable por el Orquestador (SPEC §6.4).
        PyMongoError: No se captura aquí, pero cualquier otra excepción sí sube
            intacta: un `TypeError` es un bug nuestro, no una caída de Mongo, y
            traducirlo escondería el defecto detrás de un reintento.
    """
    try:
        await client.admin.command("ping")
    except PyMongoError as exc:
        raise AuditStorageError("MongoDB is unavailable.") from exc


async def ensure_indexes(collection: Any, *, retention_days: int) -> None:
    """Crear los índices de §6.3, incluido el TTL si la retención está activa.

    Es idempotente: `create_indexes` no hace nada si el índice ya existe con las
    mismas opciones, así que este arranque se puede repetir sin riesgo.

    Args:
        collection: Colección de `audit_logs`.
        retention_days: Días de retención; decide si se crea el TTL.

    Raises:
        AuditStorageError: Si el driver rechaza la creación, por ejemplo porque
            un índice con el mismo nombre ya existe con otras opciones.
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
