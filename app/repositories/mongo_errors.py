"""Traducción de excepciones de PyMongo a errores de dominio."""

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from bson.errors import BSONError
from pymongo.errors import DocumentTooLarge, DuplicateKeyError, PyMongoError

from app.errors import AuditStorageError, PayloadTooLargeError, ValidationError
from app.repositories.protocol import ReplayDetected

T = TypeVar("T")

STORAGE_UNAVAILABLE = "MongoDB is unavailable."


def translate_pymongo_errors(func: Callable[..., T]) -> Callable[..., T]:
    """Mapea errores del driver a errores de dominio.

    - `DuplicateKeyError` (11000) → `ReplayDetected` (señal de idempotencia).
    - `DocumentTooLarge` → `PayloadTooLargeError` (413).
    - `BSONError` / `OverflowError` / `RecursionError` → `ValidationError` (400).
    - Cualquier otro `PyMongoError` → `AuditStorageError` (503).
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return await func(*args, **kwargs)
        except DuplicateKeyError as exc:
            raise ReplayDetected() from exc
        except DocumentTooLarge as exc:
            raise PayloadTooLargeError() from exc
        except (BSONError, OverflowError, RecursionError) as exc:
            raise ValidationError(
                "The 'details' field cannot be stored in MongoDB."
            ) from exc
        except PyMongoError as exc:
            raise AuditStorageError(STORAGE_UNAVAILABLE) from exc

    return wrapper
