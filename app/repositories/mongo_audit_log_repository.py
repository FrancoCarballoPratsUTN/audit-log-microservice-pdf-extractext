"""Guarda y consulta auditorías en MongoDB."""

from datetime import UTC, datetime
from typing import Any

from app.domain.models import AuditLog, CreateAuditLogRequest
from app.repositories.mongo_errors import translate_pymongo_errors
from app.repositories.serialization import to_audit_log, to_document


class MongoAuditLogRepository:
    """`AuditLogRepository` sobre una colección de MongoDB, inyectada por el
    composition root para que este módulo no conozca cliente ni configuración."""

    def __init__(self, collection: Any) -> None:
        """Guarda la colección de MongoDB que usará el repositorio.

        Args:
            collection: Colección de MongoDB.

        Returns:
            No retorna valor.
        """
        self._collection = collection

    @translate_pymongo_errors
    async def insert(self, request: CreateAuditLogRequest) -> AuditLog:
        """Guarda un evento nuevo y devuelve el registro creado.

        Args:
            request: Petición HTTP recibida.

        Returns:
            El registro guardado con su identificador y fecha de recepción.

        Raises:
            AuditStorageError: Si MongoDB no responde.
            PayloadTooLargeError: Si los detalles son demasiado grandes.
            ValidationError: Si los detalles no se pueden guardar.
        """
        document = to_document(request, received_at=datetime.now(UTC))
        await self._collection.insert_one(document)
        return to_audit_log(document)

    @translate_pymongo_errors
    async def find_replay(
        self,
        *,
        action: str,
        entity_type: str,
        checksum: str,
        performed_at: datetime,
    ) -> AuditLog | None:
        """Busca un evento con la misma identidad.

        Args:
            action: Acción realizada.
            entity_type: Tipo de entidad afectada.
            checksum: Valor que identifica el contenido.
            performed_at: Fecha y hora en que ocurrió el evento.

        Returns:
            El registro encontrado o None.
        """
        query = {
            "action": action,
            "entity_type": entity_type,
            "checksum": checksum,
            "performed_at": performed_at,
        }
        if (document := await self._collection.find_one(query)) is not None:
            return to_audit_log(document)
        return None

    @translate_pymongo_errors
    async def list(self, *, skip: int = 0, limit: int = 100) -> list[AuditLog]:
        """Devuelve una página de eventos ordenada.

        Args:
            skip: Cantidad de resultados que se van a omitir.
            limit: Cantidad máxima de resultados.

        Returns:
            La lista de registros.
        """
        cursor = (
            self._collection.find({})
            .sort([("performed_at", -1), ("_id", -1)])
            .skip(skip)
            .limit(limit)
        )
        docs = [doc async for doc in cursor]
        return [to_audit_log(doc) for doc in docs]

    @translate_pymongo_errors
    async def find_by_checksum(self, checksum: str) -> list[AuditLog]:
        """Devuelve los eventos que tienen un checksum.

        Args:
            checksum: Valor que identifica el contenido.

        Returns:
            La lista de registros coincidentes.
        """
        cursor = self._collection.find({"checksum": checksum}).sort(
            [("performed_at", -1), ("_id", -1)]
        )
        return [to_audit_log(document) async for document in cursor]


__all__ = ["MongoAuditLogRepository"]
