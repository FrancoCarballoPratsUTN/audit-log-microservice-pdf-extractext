"""Pruebas de los datos de entrada y salida."""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.api.schemas import (
    AuditEventRequest,
    AuditLogItem,
    AuditLogResponse,
    ProblemDetails,
)
from app.domain.models import AuditLog

VALID_EVENT = {
    "action": "pdf.extract",
    "entity_type": "document",
    "checksum": "9f86d081884c7d659a2feaa0c55ad015",
    "details": {"page_count": 12},
    "performed_at": "2026-10-05T12:34:56.789Z",
}


def test_valid_event_is_accepted() -> None:
    """Comprueba que un evento válido se acepta."""
    event = AuditEventRequest(**VALID_EVENT)
    assert event.action == "pdf.extract"
    assert event.entity_type == "document"
    assert event.checksum == "9f86d081884c7d659a2feaa0c55ad015"
    assert event.details == {"page_count": 12}


def test_performed_at_keeps_the_offset_of_the_emitter() -> None:
    """El instante almacenado es el reloj del emisor, no el de este servicio.
    Convertirlo a UTC aquí reescribiría en silencio lo que ocurrió.
    """
    event = AuditEventRequest(
        **{**VALID_EVENT, "performed_at": "2026-10-05T14:34:56+02:00"}
    )
    assert event.performed_at.utcoffset().total_seconds() == 7200


def test_performed_at_without_offset_is_rejected() -> None:
    """Comprueba que una fecha sin zona horaria se rechaza."""
    with pytest.raises(PydanticValidationError):
        AuditEventRequest(**{**VALID_EVENT, "performed_at": "2026-10-05T12:34:56"})


@pytest.mark.parametrize("field", ["action", "entity_type", "checksum"])
def test_empty_identifier_fields_are_rejected(field: str) -> None:
    """Comprueba que los campos identificadores vacíos se rechazan.

    Args:
        field: Nombre del campo.

    Returns:
        No retorna valor.
    """
    with pytest.raises(PydanticValidationError):
        AuditEventRequest(**{**VALID_EVENT, field: ""})


@pytest.mark.parametrize("field", ["action", "entity_type", "checksum"])
def test_missing_identifier_fields_are_rejected(field: str) -> None:
    """Comprueba que los campos identificadores ausentes se rechazan.

    Args:
        field: Nombre del campo.

    Returns:
        No retorna valor.
    """
    payload = {key: value for key, value in VALID_EVENT.items() if key != field}
    with pytest.raises(PydanticValidationError):
        AuditEventRequest(**payload)


def test_unknown_top_level_key_is_rejected() -> None:
    """`extra="forbid"`. Un `201` que deja caer `user_id` en silencio es el peor fallo
    posible en una auditoría: invisible y permanente.
    """
    with pytest.raises(PydanticValidationError):
        AuditEventRequest(**{**VALID_EVENT, "user_id": "u-1"})


def test_details_may_be_absent() -> None:
    """`text.delete` omite `details` (`omitempty` en el emisor)."""
    payload = {key: value for key, value in VALID_EVENT.items() if key != "details"}
    assert AuditEventRequest(**payload).details is None


@pytest.mark.parametrize(
    "details",
    [0, "", [], False, {"nested": {"deep": [1, 2, {"x": None}]}}, ["a", "b"], "plain"],
)
def test_details_accepts_any_json_value(details: object) -> None:
    """El emisor declara `Details any`; cualquier cosa más estrecha rechazaría las
    extensiones que el contrato ya permite.

    Args:
        details: Datos adicionales del evento.

    Returns:
        No retorna valor.
    """
    assert AuditEventRequest(**{**VALID_EVENT, "details": details}).details == details


def test_response_serializes_id_under_underscore_id() -> None:
    """Todo el sentido del alias: Go lee `ID string`."""
    payload = {
        "_id": "6f1c9a2b3d4e5f60718293a4",
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": "9f86d081884c7d659a2feaa0c55ad015",
        "details": {"page_count": 12},
        "performed_at": "2026-10-05T12:34:56.789Z",
        "received_at": "2026-10-05T12:34:57.041Z",
    }
    serialized = AuditLogResponse(**payload).model_dump(by_alias=True)

    assert serialized["_id"] == "6f1c9a2b3d4e5f60718293a4"
    assert "id" not in serialized


def test_response_carries_the_seven_fields_the_go_client_decodes() -> None:
    """Comprueba que la respuesta incluye los siete campos del cliente."""
    payload = {
        "_id": "6f1c9a2b3d4e5f60718293a4",
        "action": "text.delete",
        "entity_type": "text",
        "checksum": "9f86d081",
        "details": {},
        "performed_at": "2026-10-05T12:34:56.789Z",
        "received_at": "2026-10-05T12:34:57.041Z",
    }
    serialized = AuditLogResponse(**payload).model_dump(by_alias=True)

    assert set(serialized) >= {
        "_id",
        "action",
        "entity_type",
        "checksum",
        "details",
        "performed_at",
        "received_at",
    }


def test_response_dates_are_strings_not_datetimes() -> None:
    """El formato RFC 3339 lo pone `to_wire_fields`."""
    field = AuditLogResponse.model_fields["performed_at"]
    assert field.annotation is str


def test_response_defaults_to_a_non_replayed_creation() -> None:
    """`idempotent_replay` es un campo sólo de respuesta: nunca se persiste."""
    payload = {
        "_id": "6f1c9a2b3d4e5f60718293a4",
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": "9f86d081",
        "details": {},
        "performed_at": "2026-10-05T12:34:56.789Z",
        "received_at": "2026-10-05T12:34:57.041Z",
    }
    assert AuditLogResponse(**payload).idempotent_replay is False


def test_read_and_write_from_log_use_the_same_wire_fields() -> None:
    """Los dos `GET` y el `POST` comparten el formateador de siete campos."""
    log = AuditLog(
        id="6f1c9a2b3d4e5f60718293a4",
        action="pdf.extract",
        entity_type="document",
        checksum="9f86d081884c7d659a2feaa0c55ad015",
        performed_at=datetime(2026, 10, 5, 12, 34, 56, 789000, tzinfo=UTC),
        received_at=datetime(2026, 10, 5, 12, 34, 57, 41000, tzinfo=UTC),
        details={"page_count": 12},
    )

    item = AuditLogItem.from_log(log).model_dump(by_alias=True)
    response = AuditLogResponse.from_log(log).model_dump(by_alias=True)

    assert item == {key: response[key] for key in item}
    assert item["_id"] == "6f1c9a2b3d4e5f60718293a4"
    assert item["performed_at"] == "2026-10-05T12:34:56.789Z"
    assert item["received_at"] == "2026-10-05T12:34:57.041Z"
    assert response["idempotent_replay"] is False


def test_response_from_log_marks_a_replay() -> None:
    """Comprueba que la respuesta marca un duplicado."""
    log = AuditLog(
        id="6f1c9a2b3d4e5f60718293a4",
        action="pdf.extract",
        entity_type="document",
        checksum="9f86d081",
        performed_at=datetime(2026, 10, 5, 12, 34, 56, tzinfo=UTC),
        received_at=datetime(2026, 10, 5, 12, 34, 57, tzinfo=UTC),
        details={},
    )
    assert AuditLogResponse.from_log(log, replay=True).idempotent_replay is True


def test_problem_details_requires_the_five_canonical_members() -> None:
    """RFC 9457 §3.1 nombra cinco; `code` es la extensión de §3.2. Faltar cualquiera de
    ellos rompería el `ParseProblem` del cliente de Go.
    """
    problem = ProblemDetails(
        type="/problems/validation_error",
        title="Request validation error",
        status=400,
        detail="Field 'action' is required.",
        instance="/audit/logs",
        code="VALIDATION_ERROR",
    )
    assert set(problem.model_dump()) == {
        "type",
        "title",
        "status",
        "detail",
        "instance",
        "code",
    }


def test_problem_details_is_a_plain_model() -> None:
    """Es un cuerpo, no un objeto de dominio: no debe heredar la jerarquía de errores,
    cuyos metadatos son justamente lo que rellena estos campos.
    """
    assert issubclass(ProblemDetails, BaseModel)
    assert not issubclass(ProblemDetails, Exception)
