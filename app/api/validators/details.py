"""Validación del campo `details`"""

import json
from typing import Any

from bson import BSON
from bson.errors import BSONError

from app.errors import PayloadTooLargeError, ValidationError

BSON_MAX_NESTING = 100


def json_details(details: Any) -> bytes:
    """Serializar `details` como JSON estricto y contar sus bytes UTF-8."""
    return json.dumps(
        details,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_bson_nesting(details: Any) -> None:
    """Rechazar estructuras más profundas que el máximo de anidamiento BSON."""
    pending = [(details, 0)]
    while pending:
        value, depth = pending.pop()
        if isinstance(value, dict | list):
            depth += 1
            if depth > BSON_MAX_NESTING:
                raise ValueError("details exceeds BSON nesting depth")
            children = value.values() if isinstance(value, dict) else value
            pending.extend((child, depth) for child in children)


def validate_details(details: Any, max_bytes: int) -> None:
    """Validar que `details` es JSON/BSON válido y no excede `max_bytes`."""
    try:
        validate_bson_nesting(details)
        encoded = json_details(details)
        BSON.encode({"details": details})
    except BSONError, OverflowError, RecursionError, TypeError, ValueError:
        raise ValidationError(
            "The 'details' field is not valid JSON/BSON data."
        ) from None
    if len(encoded) > max_bytes:
        raise PayloadTooLargeError()
