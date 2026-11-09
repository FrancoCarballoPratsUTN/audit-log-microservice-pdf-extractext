"""Define los datos de entrada y salida de la API."""

from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.domain.models import AuditLog, to_wire_fields


class AuditEventRequest(BaseModel):
    """Un evento de auditoría tal como lo emite el orquestador.

    `extra="forbid"`: una clave desconocida de primer nivel se convierte en un
    `400` visible en vez de un `201` que descarta datos en silencio
    (SPEC §3.4). `details: Any` es la válvula de escape para lo que no
    merece columna ni índice.
    """

    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    details: Any = None
    performed_at: AwareDatetime


class AuditLogItem(BaseModel):
    """Un evento almacenado con exactamente los 7 campos de `models.AuditLog`
    (SPEC §2.4), lo que decodifican los dos `GET` del cliente Go.

    Sin `idempotent_replay`: ese campo sólo existe en la respuesta de
    escritura y nunca se persiste.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id", serialization_alias="_id")
    action: str
    entity_type: str
    checksum: str
    details: Any
    performed_at: str
    received_at: str

    @classmethod
    def from_log(cls, log: AuditLog) -> AuditLogItem:
        """Crea el elemento de respuesta a partir de un registro.

        Args:
            log: Registro de auditoría.

        Returns:
            El elemento con los campos del contrato.
        """
        return cls(**to_wire_fields(log))


class AuditLogResponse(AuditLogItem):
    """Un evento de auditoría almacenado con la forma que espera el
    orquestador. `idempotent_replay` existe sólo en esta respuesta."""

    idempotent_replay: bool = False

    @classmethod
    def from_log(cls, log: AuditLog, *, replay: bool = False) -> AuditLogResponse:
        """Crea la respuesta de escritura a partir de un registro.

        Args:
            log: Registro de auditoría.
            replay: Indica si el evento ya existía.

        Returns:
            La respuesta con la marca de duplicado.
        """
        return cls(**to_wire_fields(log), idempotent_replay=replay)


class ProblemDetails(BaseModel):
    """Cuerpo RFC 9457: los cinco miembros canónicos más la extensión `code`."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
