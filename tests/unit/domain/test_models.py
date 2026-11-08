def test_create_audit_log_request_converts_naive_datetime_to_utc() -> None:
    """Si `performed_at` no tiene zona horaria, se convierte a UTC (aware)."""
    from datetime import UTC, datetime

    from app.domain import models

    naive = datetime(2026, 10, 5, 12, 34, 56)
    request = models.CreateAuditLogRequest(
        action="pdf.extract",
        entity_type="document",
        checksum="abc",
        performed_at=naive,
    )

    assert request.performed_at.tzinfo == UTC


def test_audit_log_converts_naive_datetimes_to_utc() -> None:
    """`performed_at` y `received_at` sin tzinfo pasan a UTC."""
    from datetime import UTC, datetime

    from app.domain import models

    naive_performed = datetime(2026, 10, 5, 12, 34, 56)
    naive_received = datetime(2026, 10, 5, 12, 34, 57)
    audit_log = models.AuditLog(
        id="507f191e810c19729de860ea",
        action="pdf.extract",
        entity_type="document",
        checksum="abc",
        performed_at=naive_performed,
        received_at=naive_received,
    )

    assert audit_log.performed_at.tzinfo == UTC
    assert audit_log.received_at.tzinfo == UTC


def test_create_audit_log_request_truncates_performed_at_to_milliseconds() -> None:
    """La identidad usa granularidad de 1 ms: `.123456` se trunca a `.123000`."""
    from datetime import UTC, datetime

    from app.domain import models

    request = models.CreateAuditLogRequest(
        action="pdf.extract",
        entity_type="document",
        checksum="abc",
        performed_at=datetime(2026, 10, 5, 12, 34, 56, 123456, tzinfo=UTC),
    )

    assert request.performed_at == datetime(2026, 10, 5, 12, 34, 56, 123000, tzinfo=UTC)


def test_audit_log_truncates_both_timestamps_to_milliseconds() -> None:
    """`performed_at` y `received_at` se truncan a ms, sin redondear."""
    from datetime import UTC, datetime

    from app.domain import models

    audit_log = models.AuditLog(
        id="507f191e810c19729de860ea",
        action="pdf.extract",
        entity_type="document",
        checksum="abc",
        performed_at=datetime(2026, 10, 5, 12, 34, 56, 123456, tzinfo=UTC),
        received_at=datetime(2026, 10, 5, 12, 34, 57, 789600, tzinfo=UTC),
    )

    assert audit_log.performed_at == datetime(
        2026, 10, 5, 12, 34, 56, 123000, tzinfo=UTC
    )
    assert audit_log.received_at == datetime(
        2026, 10, 5, 12, 34, 57, 789000, tzinfo=UTC
    )


def test_audit_log_details_none_becomes_empty_dict() -> None:
    """Si `details` llega como `None`, se normaliza a `{}`."""
    from datetime import UTC, datetime

    from app.domain import models

    audit_log = models.AuditLog(
        id="507f191e810c19729de860ea",
        action="pdf.extract",
        entity_type="document",
        checksum="abc",
        performed_at=datetime(2026, 10, 5, 12, 34, 56, tzinfo=UTC),
        received_at=datetime(2026, 10, 5, 12, 34, 57, tzinfo=UTC),
        details=None,
    )

    assert audit_log.details == {}


def test_create_audit_log_request_details_none_becomes_empty_dict() -> None:
    """La normalización ocurre al entrar al dominio, no en cada capa."""
    from datetime import UTC, datetime

    from app.domain import models

    request = models.CreateAuditLogRequest(
        action="pdf.extract",
        entity_type="document",
        checksum="abc",
        performed_at=datetime(2026, 10, 5, 12, 34, 56, tzinfo=UTC),
        details=None,
    )

    assert request.details == {}


def test_details_are_declared_as_any_json_value() -> None:
    """El contrato acepta cualquier JSON, no sólo diccionarios."""
    from typing import Any, get_type_hints

    from app.domain import models

    assert get_type_hints(models.CreateAuditLogRequest)["details"] is Any
    assert get_type_hints(models.AuditLog)["details"] is Any


def test_to_wire_fields_returns_the_seven_fields_with_rfc3339_dates() -> None:
    """Escritura y lectura comparten este formateador de siete campos."""
    from datetime import UTC, datetime

    from app.domain import models

    log = models.AuditLog(
        id="507f191e810c19729de860ea",
        action="pdf.extract",
        entity_type="document",
        checksum="abc",
        performed_at=datetime(2026, 10, 5, 12, 34, 56, 123456, tzinfo=UTC),
        received_at=datetime(2026, 10, 5, 12, 34, 57, 654321, tzinfo=UTC),
        details={"page_count": 12},
    )

    assert models.to_wire_fields(log) == {
        "_id": "507f191e810c19729de860ea",
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": "abc",
        "details": {"page_count": 12},
        "performed_at": "2026-10-05T12:34:56.123Z",
        "received_at": "2026-10-05T12:34:57.654Z",
    }
