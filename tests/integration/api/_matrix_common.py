"""Datos y ayudas para probar la matriz de errores."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from bson import ObjectId
from fastapi.testclient import TestClient
from httpx import Response

from tests.integration.api.helpers import AUTH, VALID_EVENT
from tests.integration.conftest import COLLECTION_NAME

PROBLEM_MEDIA_TYPE = "application/problem+json"
REQUIRED_PROBLEM_MEMBERS = {"type", "title", "status", "detail"}

WRITE_REJECTING_VALIDATOR = {
    "$jsonSchema": {"required": ["__this_field_is_never_written__"]}
}


def _post_valid(client: TestClient) -> Response:
    """Envía un evento válido a la API.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        La respuesta de la API.
    """
    return client.post("/audit/logs", json=VALID_EVENT, headers=AUTH)


def _post_without_token(client: TestClient) -> Response:
    """Envía un evento sin token de acceso.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        La respuesta de la API.
    """
    return client.post("/audit/logs", json=VALID_EVENT)


def _post_unknown_key(client: TestClient) -> Response:
    """Envía un evento con un campo desconocido.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        La respuesta de la API.
    """
    return client.post(
        "/audit/logs", json={**VALID_EVENT, "user_id": "u-1"}, headers=AUTH
    )


def _post_oversized_details(client: TestClient) -> Response:
    """Envía un evento con detalles demasiado grandes.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        La respuesta de la API.
    """
    event = {**VALID_EVENT, "details": {"blob": "x" * 70000}}
    return client.post("/audit/logs", json=event, headers=AUTH)


def _post_wrong_media_type(client: TestClient) -> Response:
    """Envía el evento con un tipo de contenido incorrecto.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        La respuesta de la API.
    """
    return client.post(
        "/audit/logs",
        content=b"{}",
        headers={**AUTH, "Content-Type": "text/plain"},
    )


def _get_checksum_without_value(client: TestClient) -> Response:
    """Pide la ruta de checksum sin indicar un valor.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        El valor solicitado.
    """
    return client.get("/audit/logs/checksum/", headers=AUTH)


def _put_audit_logs(client: TestClient) -> Response:
    """Envía un método PUT a la ruta de auditorías.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        La respuesta de la API.
    """
    return client.put("/audit/logs", json=VALID_EVENT, headers=AUTH)


def _get_audit_logs(client: TestClient) -> Response:
    """Pide el listado de auditorías.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        El valor solicitado.
    """
    return client.get("/audit/logs", headers=AUTH)


async def reject_every_write(collection: Any) -> None:
    """Hace que toda escritura en MongoDB falle.

    Args:
        collection: Colección de MongoDB.

    Returns:
        No retorna valor.
    """
    await collection.database.command(
        "collMod",
        COLLECTION_NAME,
        validator=WRITE_REJECTING_VALIDATOR,
        validationLevel="strict",
    )


async def seed_a_corrupt_document(collection: Any) -> None:
    """Guarda un documento corrupto en la colección.

    Args:
        collection: Colección de MongoDB.

    Returns:
        No retorna valor.
    """
    await collection.insert_one(
        {
            "_id": ObjectId(),
            "action": "pdf.extract",
            "entity_type": "document",
            "checksum": "corrupt-0001",
            "details": {},
            "performed_at": "not-a-date",
            "received_at": "not-a-date",
        }
    )


@dataclass(frozen=True)
class Row:
    code: str
    status: int
    instance: str
    send: Callable[[TestClient], Response]
    arrange: Callable[[Any], Awaitable[None]] | None = None


ROWS = [
    Row("UNAUTHORIZED", 401, "/audit/logs", _post_without_token),
    Row("VALIDATION_ERROR", 400, "/audit/logs", _post_unknown_key),
    Row("PAYLOAD_TOO_LARGE", 413, "/audit/logs", _post_oversized_details),
    Row("UNSUPPORTED_MEDIA_TYPE", 415, "/audit/logs", _post_wrong_media_type),
    Row("NOT_FOUND", 404, "/audit/logs/checksum/", _get_checksum_without_value),
    Row("METHOD_NOT_ALLOWED", 405, "/audit/logs", _put_audit_logs),
    Row(
        "AUDIT_STORAGE_ERROR",
        503,
        "/audit/logs",
        _post_valid,
        arrange=reject_every_write,
    ),
    Row(
        "INTERNAL_ERROR",
        500,
        "/audit/logs",
        _get_audit_logs,
        arrange=seed_a_corrupt_document,
    ),
]
