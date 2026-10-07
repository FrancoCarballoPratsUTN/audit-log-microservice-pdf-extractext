"""Puerto del repositorio (Protocol).

T7 exige `AuditLogRepository` como `Protocol`. Esto define el contrato entre
la capa de servicios y la capa de acceso a datos, siguiendo DIP (SOLID). El
protocolo es `runtime_checkable` para permitir comprobaciones en tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.models import AuditLog, CreateAuditLogRequest


@runtime_checkable
class AuditLogRepository(Protocol):
    """Contrato para persistir y recuperar registros de auditoría."""

    async def insert(self, request: CreateAuditLogRequest) -> AuditLog:
        """Insertar un nuevo evento de auditoría.

        Args:
            request: Datos a persistir (sin `id` ni `received_at`).

        Returns:
            El registro persistido con su identificador y `received_at`.
        """
        ...

    async def find_replay(
        self,
        *,
        action: str,
        entity_type: str,
        checksum: str,
        performed_at: datetime,
    ) -> AuditLog | None:
        """Buscar un evento para determinar si es un replay por identidad.

        La identidad está formada por `(action, entity_type, checksum, performed_at)`.
        """
        ...

    async def find_by_checksum(self, checksum: str) -> list[AuditLog]:
        """Recuperar todos los eventos con el checksum dado.

        El orden lo decide la implementación; la capa API lo normaliza si es
        necesario para cumplir el contrato.
        """
        ...

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[AuditLog]:
        """Listar eventos con paginación.

        Args:
            skip: Número de elementos a omitir.
            limit: Número máximo de elementos a devolver.

        Returns:
            Lista de eventos (array de primer nivel).
        """
        ...

    async def count(self) -> int:
        """Contar el total de eventos."""
        ...


class ReplayDetected(Exception):
    """Señal de que el evento ya estaba almacenado (Barrera 2 de §5.3).

    No es un `ServiceError`: un replay responde `200` con el registro
    existente, y esta señal sólo le dice a la Capa 2 que repita la consulta de
    la Barrera 1. Si fuera un error de dominio, la Capa 1 la convertiría en
    problem details y el Orquestador vería un fallo donde hubo una repetición
    benigna.
    """

    def __init__(self) -> None:
        super().__init__("the audit event is already stored")


__all__ = ["AuditLogRepository", "ReplayDetected"]
