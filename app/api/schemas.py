"""Esquemas de petición y respuesta del contrato de auditoría.

`_id` necesita `serialization_alias`: FastAPI serializa con `by_alias=True`, así
que sin el alias el JSON sale con `id`, el `models.AuditLog.ID string` de Go se
queda vacío y el orquestador ve un log de auditoría sin identidad y sin error
(SPEC §2.5 H3). `tests/unit/api/test_schemas.py` falla si el alias desaparece.

`performed_at` y `received_at` son `str` a propósito. RFC 3339 con `Z` y
milisegundos no es lo que Pydantic emite para un `datetime`, y el render tiene
que llegar a Go byte a byte; el formateo lo aporta
`app/domain.models.rfc3339_utc`, la misma primitiva que usa Capa 3.
"""

from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.domain.models import AuditLog, rfc3339_utc


class AuditEventRequest(BaseModel):
    """Un evento de auditoría tal como lo emite el orquestador (`models.AuditEvent`).

    `extra="forbid"`: una clave desconocida de primer nivel se convierte en un
    `400` visible en vez de un `201` que descarta datos en silencio (SPEC §3.4).
    `details: Any` es la válvula de escape para todo lo que no se merece ni
    columna ni índice.
    """

    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    details: Any = None
    performed_at: AwareDatetime


class AuditLogResponse(BaseModel):
    """Un evento de auditoría almacenado, con la forma que espera `models.AuditLog`
    en el orquestador.

    `idempotent_replay` existe sólo en esta respuesta: nunca se persiste.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id", serialization_alias="_id")
    action: str
    entity_type: str
    checksum: str
    details: Any
    performed_at: str
    received_at: str
    idempotent_replay: bool = False

    @classmethod
    def from_log(cls, log: AuditLog, *, replay: bool = False) -> AuditLogResponse:
        """Construir la respuesta desde el registro de dominio.

        La Capa 1 no conoce Capa 3, así que no puede usar `render`: formatea
        aquí con la misma primitiva (`rfc3339_utc`) para que un solo formato
        llegue al cable.

        Args:
            log: El registro persistido, o el de un replay.
            replay: Si esta respuesta informa de una repetición idempotente.
                Es un campo de la respuesta, nunca se persiste.

        Returns:
            El cuerpo a serializar con `_id`, fechas UTC y el flag de replay.
        """
        return cls(
            id=log.id,
            action=log.action,
            entity_type=log.entity_type,
            checksum=log.checksum,
            details=log.details,
            performed_at=rfc3339_utc(log.performed_at),
            received_at=rfc3339_utc(log.received_at),
            idempotent_replay=replay,
        )


class ProblemDetails(BaseModel):
    """Cuerpo RFC 9457: los cinco miembros canónicos más la extensión `code`."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
