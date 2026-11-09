"""Ayudas comunes para probar los errores."""

from pathlib import Path

from app.errors import (
    AuditStorageError,
    InternalError,
    MethodNotAllowedError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceError,
    UnauthorizedError,
    UnsupportedMediaTypeError,
    ValidationError,
)

ERRORS_SOURCE = Path(__file__).resolve().parents[2] / "app" / "errors.py"

# (clase, status, code, type_uri, title) -- SPEC §7.2, fila por fila.
SPEC_ERROR_MATRIX: list[tuple[type[ServiceError], int, str, str, str]] = [
    (UnauthorizedError, 401, "UNAUTHORIZED", "/problems/unauthorized", "Unauthorized"),
    (
        ValidationError,
        400,
        "VALIDATION_ERROR",
        "/problems/validation_error",
        "Request validation error",
    ),
    (NotFoundError, 404, "NOT_FOUND", "/problems/not_found", "Resource not found"),
    (
        MethodNotAllowedError,
        405,
        "METHOD_NOT_ALLOWED",
        "/problems/method_not_allowed",
        "Method not allowed",
    ),
    (
        PayloadTooLargeError,
        413,
        "PAYLOAD_TOO_LARGE",
        "/problems/payload_too_large",
        "Payload too large",
    ),
    (
        UnsupportedMediaTypeError,
        415,
        "UNSUPPORTED_MEDIA_TYPE",
        "/problems/unsupported_media_type",
        "Unsupported media type",
    ),
    (
        InternalError,
        500,
        "INTERNAL_ERROR",
        "/problems/internal_error",
        "Internal server error",
    ),
    (
        AuditStorageError,
        503,
        "AUDIT_STORAGE_ERROR",
        "/problems/audit_storage_error",
        "Audit storage unavailable",
    ),
]

MATRIX_IDS = [row[0].__name__ for row in SPEC_ERROR_MATRIX]
