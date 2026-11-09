"""Define las operaciones que debe ofrecer el repositorio."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.models import AuditLog, CreateAuditLogRequest


@runtime_checkable
class AuditLogRepository(Protocol):
    """Contrato para persistir y recuperar registros de auditoría."""

    async def insert(self, request: CreateAuditLogRequest) -> AuditLog:
        """Guarda un evento nuevo.

        Args:
            request: Petición HTTP recibida.

        Returns:
            El registro guardado.
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
        """Busca un evento con la misma identidad.

        Args:
            action: Acción realizada.
            entity_type: Tipo de entidad afectada.
            checksum: Valor que identifica el contenido.
            performed_at: Fecha y hora en que ocurrió el evento.

        Returns:
            El registro encontrado o None.
        """
        ...

    async def find_by_checksum(self, checksum: str) -> list[AuditLog]:
        """Busca eventos por su checksum.

        Args:
            checksum: Valor que identifica el contenido.

        Returns:
            La lista de registros.
        """
        ...

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[AuditLog]:
        """Devuelve una página de eventos.

        Args:
            skip: Cantidad de resultados que se van a omitir.
            limit: Cantidad máxima de resultados.

        Returns:
            La lista de registros.
        """
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
        """Crea la señal de que el evento ya existía."""
        super().__init__("the audit event is already stored")


__all__ = ["AuditLogRepository", "ReplayDetected"]
