"""Capa 2: casos de uso de escritura y lectura.

Decide que el replay no es un error (SPEC §5.3): la Barrera 1 (`find_replay`)
evita la escritura en el reintento normal, y cuando la Barrera 2 responde con
`DuplicateKeyError` —la carrera resuelta por el índice único— se convierte en
el mismo resultado observable: el registro existente con `replay=True`.

En lectura, `list_page` y `list_by_checksum` trasladan a Capa 3 lo ya
validado en Capa 1; el orden lo fija el índice compuesto de SPEC §8.1.

Este módulo no conoce HTTP ni el driver: depende del `Protocol` (DIP) y lanza
errores de dominio de `app/errors.py`. `received_at` lo pica la Capa 3 con el
reloj del servidor en `insert`; aquí no hay reloj que inyectar (SPEC §5.2).
"""

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
        self._repository = repository

    async def create(self, request: CreateAuditLogRequest) -> CreateResult:
        """Persistir un evento, decidiendo si es la primera vez o un replay.

        Args:
            request: Datos del evento, tal como los validó la Capa 1.

        Returns:
            El registro existente con `replay=True`, o el recién guardado con
            `replay=False`; los dos caminos convergen en el mismo tipo.

        Raises:
            AuditStorageError: Si el índice único rechazó la identidad pero la
                relectura no encuentra el registro ganador.
        """
        identity = dict(
            action=request.action,
            entity_type=request.entity_type,
            checksum=request.checksum,
            performed_at=request.performed_at,
        )
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
        """Leer una página de eventos en el orden del contrato (SPEC §8.1)."""
        return await self._repository.list(skip=skip, limit=limit)

    async def list_by_checksum(self, checksum: str) -> list[AuditLog]:
        """Leer los eventos de un checksum en el orden del contrato (SPEC §8.1)."""
        return await self._repository.find_by_checksum(checksum)


__all__ = ["AuditLogService", "CreateResult"]
