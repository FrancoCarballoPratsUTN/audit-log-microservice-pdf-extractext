"""Serialización: el único punto donde BSON se cruza con el dominio y con el
JSON de la API.

Si este mapeo se desparrama por los endpoints, cada uno acaba emitiendo fechas
con un formato distinto (con y sin milisegundos, `+00:00` en vez de `Z`) y el
orquestador acepta unas y rechaza otras sin que el servicio se entere. Por eso
las fechas y el `ObjectId` se fijan aquí, byte a byte, y no en un test de
contrato lejano (SPEC §2.4 y §6.2).
"""

from datetime import UTC, datetime, timedelta, timezone

from bson import ObjectId

from app.domain.models import AuditLog, CreateAuditLogRequest
from app.repositories.serialization import render, to_audit_log, to_document

PERFORMED_AT = datetime(2026, 10, 5, 12, 34, 56, 789000, tzinfo=UTC)
CHECKSUM = "9f86d081884c7d659a2feaa0c55ad015"
WIRE_ID = "68e2c1f4a1b2c3d4e5f60718"


def make_request(**overrides: object) -> CreateAuditLogRequest:
    """Petición válida, con lo que pida el test cambiado."""
    values: dict[str, object] = {
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
        "performed_at": PERFORMED_AT,
    }
    values.update(overrides)
    return CreateAuditLogRequest(**values)


def make_document(**overrides: object) -> dict[str, object]:
    """Documento como lo devuelve Mongo: `_id` ya asignado y fechas *naive*,
    que es lo que PyMongo devuelve por defecto (UTC sin avisar)."""
    document: dict[str, object] = {
        "_id": ObjectId(),
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
        "details": {"page_count": 12},
        "performed_at": PERFORMED_AT.replace(tzinfo=None),
        "received_at": datetime(2026, 10, 5, 12, 34, 57, 41000),
    }
    document.update(overrides)
    return document


def make_log(**overrides: object) -> AuditLog:
    """Registro de dominio listo para renderizar."""
    values: dict[str, object] = {
        "id": WIRE_ID,
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
        "performed_at": PERFORMED_AT,
        "received_at": datetime(2026, 10, 5, 12, 34, 57, 41000, tzinfo=UTC),
        "details": {"page_count": 12},
    }
    values.update(overrides)
    return AuditLog(**values)


def test_to_document_assigns_an_object_id() -> None:
    """El `_id` lo genera Mongo con su `ObjectId`: un hex inventado por
    nosotros no tiene el mismo orden lexicográfico por fecha que el de verdad,
    y el desempate por `_id desc` de §12 dejaría de ser estable."""
    document = to_document(make_request(), received_at=PERFORMED_AT)

    assert isinstance(document["_id"], ObjectId)


def test_to_document_keeps_the_identity_fields_verbatim() -> None:
    """La identidad de §6.3 son cuatro campos; ninguno se normaliza ni se
    recorta al guardar."""
    request = make_request()

    document = to_document(request, received_at=PERFORMED_AT)

    assert document["action"] == request.action
    assert document["entity_type"] == request.entity_type
    assert document["checksum"] == request.checksum
    assert document["performed_at"] == request.performed_at


def test_to_document_stamps_received_at_with_the_given_clock() -> None:
    """`received_at` lo pica el llamante con el reloj del servidor; el
    `performed_at` del evento no se toca en ningún caso."""
    received_at = datetime.now(UTC)

    document = to_document(make_request(), received_at=received_at)

    assert document["received_at"] == received_at


def test_to_document_stores_details_exactly_as_given() -> None:
    """`details` es un JSON arbitrario: claves con punto, claves con dólar,
    anidación. Aquí se guarda tal cual, sin interpretarlo (SPEC §6.2)."""
    details = {"page_count": 12, "nested.key": {"$ref": "x"}}

    document = to_document(make_request(details=details), received_at=PERFORMED_AT)

    assert document["details"] == details


def test_to_document_writes_an_empty_object_when_details_are_absent() -> None:
    """SPEC §6.2: el campo no admite `null`; si la petición no trae
    `details`, el documento lleva `{}`."""
    document = to_document(make_request(details=None), received_at=PERFORMED_AT)

    assert document["details"] == {}


def test_to_document_does_not_replace_falsy_details() -> None:
    """`or {}` convertiría una lista vacía en `{}` y perdería el contenido en
    silencio: sólo la ausencia se rellena, el resto va verbatim."""
    document = to_document(make_request(details=[]), received_at=PERFORMED_AT)

    assert document["details"] == []


def test_to_audit_log_uses_the_object_id_hex_as_id() -> None:
    """El orquestador espera `id` como string de 24 caracteres hexadecimales,
    no un subdocumento `{"$oid": ...}` (SPEC §2.4)."""
    document = make_document()

    log = to_audit_log(document)

    assert log.id == str(document["_id"])
    assert len(log.id) == 24


def test_to_audit_log_makes_naive_dates_utc_aware() -> None:
    """PyMongo devuelve datetimes *naive* interpretados en UTC: sin ese paso,
    `AuditLog` los trataría como hora local de la máquina y `render` los
    desplazaría horas."""
    log = to_audit_log(make_document())

    assert log.performed_at == PERFORMED_AT
    assert log.received_at == datetime(2026, 10, 5, 12, 34, 57, 41000, tzinfo=UTC)
    assert log.performed_at.tzinfo is not None
    assert log.received_at.tzinfo is not None


def test_to_audit_log_turns_null_details_into_an_empty_dict() -> None:
    log = to_audit_log(make_document(details=None))

    assert log.details == {}


def test_to_audit_log_defaults_details_when_the_field_is_missing() -> None:
    """Un documento escrito por una versión anterior sin el campo no debe
    romper la lectura."""
    document = make_document()
    del document["details"]

    log = to_audit_log(document)

    assert log.details == {}


def test_the_round_trip_preserves_every_stored_field() -> None:
    """Documento → dominio sin pérdidas: lo que se guarda es lo que se lee,
    que es lo que después audita alguien."""
    document = make_document()

    log = to_audit_log(document)

    assert log.action == document["action"]
    assert log.entity_type == document["entity_type"]
    assert log.checksum == document["checksum"]
    assert log.details == document["details"]


def test_render_returns_exactly_the_seven_wire_fields() -> None:
    """SPEC §2.4 enumera siete campos. Aquí se fija el conjunto exacto: un
    campo de más o de menos desvía el contrato del orquestador."""
    assert set(render(make_log())) == {
        "_id",
        "action",
        "entity_type",
        "checksum",
        "details",
        "performed_at",
        "received_at",
    }


def test_render_formats_the_dates_as_rfc3339_utc_with_z() -> None:
    """El formato byte a byte de SPEC §2.4: `Z` y milisegundos. `+00:00` o
    seis decimales no los parsea `time.Time` del orquestador."""
    rendered = render(make_log())

    assert rendered["performed_at"] == "2026-10-05T12:34:56.789Z"
    assert rendered["received_at"] == "2026-10-05T12:34:57.041Z"


def test_render_converts_any_offset_to_utc_before_formatting() -> None:
    """Una petición con `+02:00` llega normalizada al dominio, pero el render
    no debe fiarse de eso: convierte siempre."""
    log = make_log(
        performed_at=datetime(
            2026, 10, 5, 14, 34, 56, tzinfo=timezone(timedelta(hours=2))
        )
    )

    assert render(log)["performed_at"] == "2026-10-05T12:34:56.000Z"


def test_render_truncates_sub_millisecond_precision() -> None:
    """Mongo guarda microsegundos y el contrato sólo promete milisegundos:
    truncar, no redondear (`.7896` → `.789`, nunca `.790`)."""
    log = make_log(performed_at=datetime(2026, 10, 5, 12, 34, 56, 789600, tzinfo=UTC))

    assert render(log)["performed_at"] == "2026-10-05T12:34:56.789Z"


def test_render_keeps_the_id_and_details_intact() -> None:
    """`_id` sale como string plano y `details` sin tocar: render no debe
    reinterpretar lo que ya interpretó `to_audit_log`."""
    details = {"page_count": 12, "nested": {"$ref": "x"}}

    rendered = render(make_log(details=details))

    assert rendered["_id"] == WIRE_ID
    assert rendered["details"] == details
