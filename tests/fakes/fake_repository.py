"""Doble en memoria de `AuditLogRepository`."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.domain.models import AuditLog, CreateAuditLogRequest


class FakeAuditLogRepository:
    """Implementación en memoria que cumple el contrato del repositorio."""

    def __init__(
        self,
        items: list[AuditLog] | None = None,
        *,
        insert_error: Exception | None = None,
        find_replay_error: Exception | None = None,
        find_by_checksum_error: Exception | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self._items: list[AuditLog] = list(items or [])
        self.insert_error = insert_error
        self.find_replay_error = find_replay_error
        self.find_by_checksum_error = find_by_checksum_error
        self.list_error = list_error
        self.insert_calls = 0
        self.find_replay_calls = 0

    async def insert(self, request: CreateAuditLogRequest) -> AuditLog:
        """Inserta un nuevo evento, asignando `id` y `received_at`.

        El `id` es un UUID único; los tests no dependen de su valor.
        """
        if self.insert_error is not None:
            raise self.insert_error

        self.insert_calls += 1
        received_at = datetime.now(UTC)
        audit_log = AuditLog(
            id=str(uuid4()),
            action=request.action,
            entity_type=request.entity_type,
            checksum=request.checksum,
            performed_at=request.performed_at,
            received_at=received_at,
            details=request.details,
        )
        self._items.append(audit_log)
        return audit_log

    async def find_replay(
        self,
        *,
        action: str,
        entity_type: str,
        checksum: str,
        performed_at: datetime,
    ) -> AuditLog | None:
        """Busca un evento con identidad exacta."""
        if self.find_replay_error is not None:
            raise self.find_replay_error

        self.find_replay_calls += 1

        def _matches(log: AuditLog) -> bool:
            return (
                log.action == action
                and log.entity_type == entity_type
                and log.checksum == checksum
                and log.performed_at == performed_at
            )

        for log in self._items:
            if _matches(log):
                return log
        return None

    async def find_by_checksum(self, checksum: str) -> list[AuditLog]:
        """Filtra por checksum conservando el orden de inserción del fake."""
        if self.find_by_checksum_error is not None:
            raise self.find_by_checksum_error

        return [log for log in self._items if log.checksum == checksum]

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[AuditLog]:
        """Devuelve una página ordenada por `performed_at` desc, luego por `id`."""
        if self.list_error is not None:
            raise self.list_error

        sorted_items = sorted(
            self._items,
            key=lambda log: (-log.performed_at.timestamp(), log.id),
        )
        return sorted_items[skip : skip + limit]


__all__ = ["FakeAuditLogRepository"]
