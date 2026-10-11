"""Capa 3: el repositorio sobre MongoDB.

Cumple el contrato de `protocol.AuditLogRepository` estructuralmente: hoy
`insert`, `find_replay`, `list` (T12) y `find_by_checksum` (T13); `count` queda
como capacidad del puerto aún sin uso.

Traduce las excepciones del driver según SPEC §6.4 y sólo esas:
`DuplicateKeyError` es la señal de replay (Barrera 2 de §5.3), `DocumentTooLarge`
es `413`, y el resto de `PyMongoError` es `503` con un `detail` nuestro, nunca
el del driver, que trae `host:port` y a veces la URI entera. Cualquier otra
excepción sube intacta: un `TypeError` es un bug nuestro, y convertirlo en un
error de almacenamiento escondería el defecto detrás de un reintento que no
puede arreglarlo.

No importa nada de `app.api` ni de `app.services`: la dependencia apunta hacia
adentro y el cableado lo hace el composition root (`app/main.py`), como verifica
`tests/unit/test_package_layout.py`.
"""

from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DocumentTooLarge, DuplicateKeyError, PyMongoError

from app.domain.models import AuditLog, CreateAuditLogRequest
from app.errors import AuditStorageError, PayloadTooLargeError
from app.repositories.protocol import ReplayDetected
from app.repositories.serialization import to_audit_log, to_document

STORAGE_UNAVAILABLE = "MongoDB is unavailable."


class MongoAuditLogRepository:
    """`AuditLogRepository` sobre una colección de MongoDB, inyectada por el
    composition root para que este módulo no conozca cliente ni configuración."""

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    async def insert(self, request: CreateAuditLogRequest) -> AuditLog:
        """Guardar un evento nuevo, asignando `_id` y `received_at`.

        Args:
            request: Datos a persistir (sin `id` ni `received_at`).

        Returns:
            El registro persistido con su identificador y `received_at`.

        Raises:
            ReplayDetected: Si el índice único rechaza la identidad (11000).
                No es un fallo: la Capa 2 la convierte en el mismo `200` que
                produce la Barrera 1 (SPEC §5.3).
            PayloadTooLargeError: Si el documento supera los 16 MiB de BSON
                (SPEC §6.4), el mismo `413` que el límite de body.
            AuditStorageError: Cualquier otro fallo del driver: `503`
                reintentable, con detalle propio y sin `host:port`.
        """
        document = to_document(request, received_at=datetime.now(UTC))
        try:
            await self._collection.insert_one(document)
        except DuplicateKeyError as exc:
            raise ReplayDetected() from exc
        except DocumentTooLarge as exc:
            raise PayloadTooLargeError() from exc
        except PyMongoError as exc:
            raise AuditStorageError(STORAGE_UNAVAILABLE) from exc
        return to_audit_log(document)

    async def find_replay(
        self,
        *,
        action: str,
        entity_type: str,
        checksum: str,
        performed_at: datetime,
    ) -> AuditLog | None:
        """Buscar un evento por su identidad exacta de §6.3 (Barrera 1).

        Args:
            action: Acción del evento.
            entity_type: Tipo de entidad afectada.
            checksum: Suma de verificación del contenido.
            performed_at: Instante en que ocurrió la acción.

        Returns:
            El registro existente, o `None` si la identidad no está almacenada.

        Raises:
            AuditStorageError: Si el driver falla al leer, con el mismo criterio
                que `insert`: quien no puede leer tampoco puede decidir si hay
                replay.
        """
        try:
            document = await self._collection.find_one(
                {
                    "action": action,
                    "entity_type": entity_type,
                    "checksum": checksum,
                    "performed_at": performed_at,
                }
            )
        except PyMongoError as exc:
            raise AuditStorageError(STORAGE_UNAVAILABLE) from exc
        if document is None:
            return None
        return to_audit_log(document)

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[AuditLog]:
        """Leer una página ordenada `performed_at desc, _id desc` (SPEC §8.1).

        El orden se fija aquí, junto al índice compuesto de §6.3 que lo
        respalda: sin `_id` en la clave de orden, dos eventos con el mismo
        `performed_at` podían paginar de forma no determinista entre dos
        llamadas con el mismo `skip`/`limit`.

        Args:
            skip: Elementos a omitir.
            limit: Tamaño máximo de la página.

        Returns:
            Los registros de la página, con `_id` en hex de 24 caracteres y
            fechas UTC; vacío si no hay coincidencias.

        Raises:
            AuditStorageError: Si el driver falla al leer o al iterar el
                cursor, con el mismo criterio que `insert`.
        """
        try:
            cursor = (
                self._collection.find({})
                .sort([("performed_at", -1), ("_id", -1)])
                .skip(skip)
                .limit(limit)
            )
            return [to_audit_log(document) async for document in cursor]
        except PyMongoError as exc:
            raise AuditStorageError(STORAGE_UNAVAILABLE) from exc

    async def find_by_checksum(self, checksum: str) -> list[AuditLog]:
        """Leer los eventos de un checksum, ordenados como el índice §6.3.

        El filtro es igualdad exacta sobre un checksum **opaco** (SPEC §5.2):
        no se normaliza ni se valida el formato. El orden `performed_at desc,
        _id desc` es el del índice compuesto `(checksum, performed_at desc,
        _id desc)`, así que Mongo lo sirve sin ordenar en memoria, y el `_id`
        garantiza el desempate estable. Sin `.skip()`/`.limit()` a propósito:
        el cliente Go no pagina este listado (D12).

        Args:
            checksum: El checksum a filtrar, tal como llega del path.

        Returns:
            Los registros de ese checksum, con `_id` en hex y fechas UTC;
            vacío si no hay coincidencias.

        Raises:
            AuditStorageError: Si el driver falla al leer o al iterar el
                cursor, con el mismo criterio que `list`.
        """
        try:
            cursor = self._collection.find({"checksum": checksum}).sort(
                [("performed_at", -1), ("_id", -1)]
            )
            return [to_audit_log(document) async for document in cursor]
        except PyMongoError as exc:
            raise AuditStorageError(STORAGE_UNAVAILABLE) from exc


__all__ = ["MongoAuditLogRepository"]
