"""Revisa que los detalles se puedan guardar."""

import json
from typing import Any

from bson import BSON
from bson.errors import BSONError

from app.errors import PayloadTooLargeError, ValidationError

BSON_MAX_NESTING = 100


def json_details(details: Any) -> bytes:
    """Convierte los detalles a JSON y cuenta sus bytes.

    Args:
        details: Datos adicionales del evento.

    Returns:
        Los detalles codificados en UTF-8.
    """
    return json.dumps(
        details,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_bson_nesting(details: Any) -> None:
    """Rechaza detalles con demasiados niveles.

    Args:
        details: Datos adicionales del evento.

    Returns:
        No retorna valor.

    Raises:
        ValueError: Si los detalles superan la profundidad permitida.
    """
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
    """Comprueba que los detalles se puedan guardar y no sean muy grandes.

    Args:
        details: Datos adicionales del evento.
        max_bytes: Tamaño máximo permitido.

    Returns:
        No retorna valor.

    Raises:
        ValidationError: Si los detalles no se pueden guardar.
        PayloadTooLargeError: Si los detalles superan el tamaño máximo.
    """
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
