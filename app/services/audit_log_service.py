"""Capa 2: el caso de uso de escritura.

Punto único donde se decide que el replay no es un error (SPEC §5.3): la
Barrera 1 (`find_replay`) evita el viaje de escritura en el reintento normal,
y cuando la Barrera 2 responde con la señal de `DuplicateKeyError` —la carrera
resuelta por el índice único— este servicio la convierte en el **mismo**
resultado observable: el registro existente con `replay=True`. La Capa 1
responderá el mismo `200` por ambos caminos.

Este módulo no conoce HTTP ni el driver: depende del `Protocol` (DIP) y lanza
errors de dominio de `app/errors.py`. `received_at` lo pica la Capa 3 con el
reloj del servidor en `insert`; aquí no hay reloj que inyectar (SPEC §5.2).
"""

from dataclasses import dataclass

from app.domain.models import AuditLog, CreateAuditLogRequest
from app.errors import AuditStorageError
from app.repositories.protocol import AuditLogRepository, ReplayDetected


@dataclass(frozen=True, slots=True)
class CreateResult:
    """El resultado observable del caso de uso: el log y si fue un replay.

    Attributes:
        log: El registro existente (replay) o el recién insertado.
        replay: `True` si el evento ya estaba almacenado. La Capa 1 lo
            traduce a la misma respuesta `200` idempotente, no a un error.
    """

    log: AuditLog
    replay: bool


class AuditLogService:
    """Servicio del caso de uso de escritura, sin estado propio."""

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
                relectura no encuentra el registro ganador: almacenamiento
                incoherente, `503` reintentable.
        """
        existing = await self._find_existing(request)
        if existing is not None:
            return CreateResult(existing, replay=True)

        try:
            log = await self._repository.insert(request)
        except ReplayDetected as exc:
            winner = await self._find_existing(request)
            if winner is None:
                raise AuditStorageError(
                    "The stored duplicate could not be read back."
                ) from exc
            return CreateResult(winner, replay=True)

        return CreateResult(log, replay=False)

    async def _find_existing(self, request: CreateAuditLogRequest) -> AuditLog | None:
        """La consulta de la Barrera 1: identidad exacta de §6.3."""
        return await self._repository.find_replay(
            action=request.action,
            entity_type=request.entity_type,
            checksum=request.checksum,
            performed_at=request.performed_at,
        )


__all__ = ["AuditLogService", "CreateResult"]
