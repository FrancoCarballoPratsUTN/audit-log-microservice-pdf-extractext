"""Gestiona la creación y consulta de auditorías."""

from dataclasses import dataclass

from app.domain.models import AuditLog, CreateAuditLogRequest
from app.errors import AuditStorageError
from app.repositories.protocol import AuditLogRepository, ReplayDetected


@dataclass(frozen=True, slots=True)
class CreateResult:
    """Resultado del caso de uso: el log y si fue un replay."""

    log: AuditLog
    replay: bool


class AuditLogService:
    """Casos de uso de escritura y lectura, sin estado propio."""

    def __init__(self, repository: AuditLogRepository) -> None:
        """Guarda el repositorio que usará el servicio.

        Args:
            repository: Repositorio de auditorías.

        Returns:
            No retorna valor.
        """
        self._repository = repository

    async def create(self, request: CreateAuditLogRequest) -> CreateResult:
        """Guarda un evento o devuelve el que ya existía.

        Args:
            request: Petición HTTP recibida.

        Returns:
            El registro y la marca de si era un duplicado.

        Raises:
            AuditStorageError: Si el repositorio no puede guardar el evento.
        """
        identity = {
            "action": request.action,
            "entity_type": request.entity_type,
            "checksum": request.checksum,
            "performed_at": request.performed_at,
        }
        existing = await self._repository.find_replay(**identity)
        if existing is not None:
            return CreateResult(existing, replay=True)

        try:
            log = await self._repository.insert(request)
        except ReplayDetected as exc:
            winner = await self._repository.find_replay(**identity)
            if winner is None:
                raise AuditStorageError(
                    "The stored duplicate could not be read back."
                ) from exc
            return CreateResult(winner, replay=True)

        return CreateResult(log, replay=False)

    async def list_page(self, *, skip: int, limit: int) -> list[AuditLog]:
        """Devuelve una página de eventos.

        Args:
            skip: Cantidad de resultados que se van a omitir.
            limit: Cantidad máxima de resultados.

        Returns:
            La lista de registros.
        """
        return await self._repository.list(skip=skip, limit=limit)

    async def list_by_checksum(self, checksum: str) -> list[AuditLog]:
        """Devuelve los eventos de un checksum.

        Args:
            checksum: Valor que identifica el contenido.

        Returns:
            La lista de registros.
        """
        return await self._repository.find_by_checksum(checksum)


__all__ = ["AuditLogService", "CreateResult"]
