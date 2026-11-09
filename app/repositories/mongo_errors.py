"""Traduce los errores de MongoDB a errores del servicio."""
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
    """Convierte los errores de PyMongo en errores del servicio.

    Args:
        func: Función que se va a proteger.

    Returns:
        La función con los errores traducidos.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        """Ejecuta la función y traduce sus errores.

        Args:
            *args: Argumentos adicionales.
            **kwargs: Argumentos adicionales.

        Returns:
            El resultado de la función.
        """
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
