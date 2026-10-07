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
        details=None,  # type: ignore[arg-type]
    )

    assert audit_log.details == {}
