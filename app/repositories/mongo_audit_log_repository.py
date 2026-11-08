from datetime import UTC, datetime
from typing import Any

from app.domain.models import AuditLog, CreateAuditLogRequest
from app.repositories.mongo_errors import translate_pymongo_errors
from app.repositories.serialization import to_audit_log, to_document


class MongoAuditLogRepository:
    """`AuditLogRepository` sobre una colección de MongoDB, inyectada por el
    composition root para que este módulo no conozca cliente ni configuración."""

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    @translate_pymongo_errors
    async def insert(self, request: CreateAuditLogRequest) -> AuditLog:
        """Guardar un evento nuevo, asignando `_id` y `received_at`."""
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
        """Buscar un evento por su identidad para detectar replays."""
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
        """Leer una página ordenada `performed_at desc, _id desc`"""
        docs = (
            await self._collection.find({})
            .sort([("performed_at", -1), ("_id", -1)])
            .skip(skip)
            .limit(limit)
            .to_list(limit)
        )
        return [to_audit_log(doc) for doc in docs]

    @translate_pymongo_errors
    async def find_by_checksum(self, checksum: str) -> list[AuditLog]:
        """Leer los eventos de un checksum, ordenados como el índice"""
        cursor = self._collection.find({"checksum": checksum}).sort(
            [("performed_at", -1), ("_id", -1)]
        )
        return [to_audit_log(document) async for document in cursor]


__all__ = ["MongoAuditLogRepository"]
