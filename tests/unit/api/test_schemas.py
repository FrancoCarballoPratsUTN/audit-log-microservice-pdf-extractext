"""Esquemas: la forma del contrato de la API.

Tres modelos, una función cada uno: lo que envía el emisor, lo que devuelve este
servicio y cómo se ve un error en el cable (RFC 9457).

Dos decisiones de aquí protegen al cliente de Go, y ambas son invisibles cuando
funcionan:

- `_id` se declara con `serialization_alias`. Sin él Pydantic emite `id`, el
  `models.AuditLog.ID string` de Go se queda vacío y **nada falla en voz alta**
  (SPEC §2.5 H3).
- `details` es `Any`, no `dict`. El campo del emisor es `any` (SPEC §2.5 H4), y
  estrecharlo rechazaría justamente las extensiones que el contrato permite.
"""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.api.schemas import AuditEventRequest, AuditLogResponse, ProblemDetails
from app.domain.models import AuditLog

VALID_EVENT = {
    "action": "pdf.extract",
    "entity_type": "document",
    "checksum": "9f86d081884c7d659a2feaa0c55ad015",
    "details": {"page_count": 12},
    "performed_at": "2026-10-05T12:34:56.789Z",
}


def test_valid_event_is_accepted() -> None:
    event = AuditEventRequest(**VALID_EVENT)
    assert event.action == "pdf.extract"
    assert event.entity_type == "document"
    assert event.checksum == "9f86d081884c7d659a2feaa0c55ad015"
    assert event.details == {"page_count": 12}


def test_performed_at_keeps_the_offset_of_the_emitter() -> None:
    """El instante almacenado es el reloj del emisor, no el de este servicio.
    Convertirlo a UTC aquí reescribiría en silencio lo que ocurrió (SPEC §5.4)."""
    event = AuditEventRequest(
        **{**VALID_EVENT, "performed_at": "2026-10-05T14:34:56+02:00"}
    )
    assert event.performed_at.utcoffset().total_seconds() == 7200


def test_performed_at_without_offset_is_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        AuditEventRequest(**{**VALID_EVENT, "performed_at": "2026-10-05T12:34:56"})


@pytest.mark.parametrize("field", ["action", "entity_type", "checksum"])
def test_empty_identifier_fields_are_rejected(field: str) -> None:
    with pytest.raises(PydanticValidationError):
        AuditEventRequest(**{**VALID_EVENT, field: ""})


@pytest.mark.parametrize("field", ["action", "entity_type", "checksum"])
def test_missing_identifier_fields_are_rejected(field: str) -> None:
    payload = {key: value for key, value in VALID_EVENT.items() if key != field}
    with pytest.raises(PydanticValidationError):
        AuditEventRequest(**payload)


def test_unknown_top_level_key_is_rejected() -> None:
    """`extra="forbid"` (SPEC §3.4). Un `201` que deja caer `user_id` en
    silencio es el peor fallo posible en una auditoría: invisible y
    permanente."""
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
    extensiones que el contrato ya permite (SPEC §2.5 H4)."""
    assert AuditEventRequest(**{**VALID_EVENT, "details": details}).details == details


def test_response_serializes_id_under_underscore_id() -> None:
    """Todo el sentido del alias: Go lee `ID string` (SPEC §2.5 H3)."""
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
    """El render RFC 3339 es de `app/repositories/serialization.py`. Dejar que
    Pydantic reformatee un `datetime` arriesgaría un `+00:00` o relleno de
    microsegundos, y el formato tiene que llegar a Go byte a byte."""
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


def test_response_from_log_renders_dates_and_id_like_the_repository() -> None:
    """El router construye la respuesta desde el dominio; el alias `_id`, las
    fechas RFC 3339 con `Z` y el campo extra tienen que salir byte a byte como
    en `render` de Capa 3, para que un solo formato llegue al cable."""
    log = AuditLog(
        id="6f1c9a2b3d4e5f60718293a4",
        action="pdf.extract",
        entity_type="document",
        checksum="9f86d081884c7d659a2feaa0c55ad015",
        performed_at=datetime(2026, 10, 5, 12, 34, 56, 789000, tzinfo=UTC),
        received_at=datetime(2026, 10, 5, 12, 34, 57, 41000, tzinfo=UTC),
        details={"page_count": 12},
    )

    serialized = AuditLogResponse.from_log(log).model_dump(by_alias=True)

    assert serialized["_id"] == "6f1c9a2b3d4e5f60718293a4"
    assert serialized["performed_at"] == "2026-10-05T12:34:56.789Z"
    assert serialized["received_at"] == "2026-10-05T12:34:57.041Z"
    assert serialized["idempotent_replay"] is False


def test_response_from_log_marks_a_replay() -> None:
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
    """RFC 9457 §3.1 nombra cinco; `code` es la extensión de §3.2. Faltar cualquiera
    de ellos rompería el `ParseProblem` del cliente de Go (SPEC §2.6)."""
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
    """Es un cuerpo, no un objeto de dominio: no debe heredar la jerarquía de
    errores, cuyos metadatos son justamente lo que rellena estos campos."""
    assert issubclass(ProblemDetails, BaseModel)
    assert not issubclass(ProblemDetails, Exception)
