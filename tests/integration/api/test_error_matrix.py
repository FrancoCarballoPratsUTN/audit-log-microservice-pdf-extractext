"""T15: la matriz de errores completa (SPEC §7.2), de punta a punta.

Cada fila de §7.2 la produce una capa distinta — el middleware de auth, el de
content-type, el de tamaño, el enrutado, el handler de último recurso o el driver
de Mongo —, así que la única forma de saber que ninguna se cuela es pedirle las
ocho al mismo cliente real. Un `422` o un `500` donde tocaba un `400` rompe al
orquestador (SPEC §2.6), y no se ve mirando una capa aislada.

Los dos fallos de almacenamiento se inyectan en la propia base de datos, nunca
con `patch` sobre `app/`: un validador de colección que rechaza toda escritura
(el driver lanza `WriteError`, un `PyMongoError`, que el repositorio traduce a
`503`) y un documento corrupto sembrado a mano (que revienta al reconstruir el
modelo de dominio, fuera de cualquier `except PyMongoError`, y sube al handler de
último recurso como `500`). Parchear `app/` obligaría al test a estar de acuerdo
con el código sobre dónde vive el fallo, que es justo lo que no debe asumir.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from httpx import Response

from tests.integration.conftest import COLLECTION_NAME, TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}

VALID_EVENT = {
    "action": "pdf.extract",
    "entity_type": "document",
    "checksum": "9f86d081884c7d659a2feaa0c55ad015",
    "details": {"page_count": 12},
    "performed_at": "2026-10-05T12:34:56.789Z",
}

PROBLEM_MEDIA_TYPE = "application/problem+json"

# Lo mínimo que `httpclient/client.go` parsea de todo cuerpo con `status >= 300`
# (SPEC §2.6). `instance` y `code` los añade este servicio, pero los cuatro
# primeros son la condición de que el orquestador no reviente.
REQUIRED_PROBLEM_MEMBERS = {"type", "title", "status", "detail"}

# Un validador de colección que exige un campo que el modelo de dominio nunca
# escribe: convierte cualquier `insert_one` en un `WriteError` de servidor.
WRITE_REJECTING_VALIDATOR = {
    "$jsonSchema": {"required": ["__this_field_is_never_written__"]}
}


def _post_valid(client: TestClient) -> Response:
    return client.post("/audit/logs", json=VALID_EVENT, headers=AUTH)


def _post_without_token(client: TestClient) -> Response:
    return client.post("/audit/logs", json=VALID_EVENT)


def _post_unknown_key(client: TestClient) -> Response:
    return client.post(
        "/audit/logs", json={**VALID_EVENT, "user_id": "u-1"}, headers=AUTH
    )


def _post_oversized_details(client: TestClient) -> Response:
    event = {**VALID_EVENT, "details": {"blob": "x" * 70000}}
    return client.post("/audit/logs", json=event, headers=AUTH)


def _post_wrong_media_type(client: TestClient) -> Response:
    return client.post(
        "/audit/logs",
        content=b"{}",
        headers={**AUTH, "Content-Type": "text/plain"},
    )


def _get_checksum_without_value(client: TestClient) -> Response:
    return client.get("/audit/logs/checksum/", headers=AUTH)


def _put_audit_logs(client: TestClient) -> Response:
    return client.put("/audit/logs", json=VALID_EVENT, headers=AUTH)


def _get_audit_logs(client: TestClient) -> Response:
    return client.get("/audit/logs", headers=AUTH)


async def reject_every_write(collection: Any) -> None:
    """Añadir a la colección un validador que rechaza todas las escrituras.

    `collMod` y no `create_collection`: el lifespan de la app ya creó la
    colección al crear sus índices, así que el fallo se inyecta sobre la base
    real que el repositorio va a usar, no sobre una copia.
    """
    await collection.database.command(
        "collMod",
        COLLECTION_NAME,
        validator=WRITE_REJECTING_VALIDATOR,
        validationLevel="strict",
    )


async def seed_a_corrupt_document(collection: Any) -> None:
    """Sembrar un documento que el modelo de dominio no puede reconstruir.

    `performed_at` es un `str` donde se espera un `datetime`: al listar, Capa 3
    lo pasa a `AuditLog`, que intenta normalizarlo a UTC y lanza `AttributeError`
    — fuera de `except PyMongoError`, así que es un `500`, no un `503`.
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
    """Una fila de la matriz: qué pedir, qué status/code esperar y con qué
    preparar la base antes."""

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


@pytest.mark.parametrize("row", ROWS, ids=[row.code for row in ROWS])
async def test_every_row_of_the_matrix(
    row: Row, deployed: None, clean_collection: object, app_client: TestClient
) -> None:
    """Las ocho filas de SPEC §7.2, con su status y su `code` exactos, y la regla
    de `httpclient/client.go:39`: todo `>= 300` trae un problem details con `type`,
    `title`, `status` y `detail` (SPEC §2.6)."""
    if row.arrange is not None:
        await row.arrange(clean_collection)

    response = row.send(app_client)

    assert response.status_code == row.status
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)

    body = response.json()
    assert body["code"] == row.code
    assert body["status"] == row.status
    assert body["instance"] == row.instance
    assert set(body) >= REQUIRED_PROBLEM_MEMBERS


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_put_and_delete_on_the_collection_are_405(
    method: str, deployed: None, app_client: TestClient
) -> None:
    """Un log de auditoría es append-only (SPEC §6.2): los dos verbos de mutación
    sobre `/audit/logs` responden `405`, no `404` ni `405` sin cuerpo."""
    response = app_client.request(method, "/audit/logs", json=VALID_EVENT, headers=AUTH)

    assert response.status_code == 405
    assert response.json()["code"] == "METHOD_NOT_ALLOWED"


def test_no_route_ever_answers_422(deployed: None, app_client: TestClient) -> None:
    """La garantía negativa que sostiene todo lo demás (SPEC §3.3 D1, §2.6): el
    `422` de FastAPI no sale nunca, ni siquiera ante JSON malformado, un cuerpo
    que no es objeto o un `skip`/`limit` fuera de rango. Todos son `400`."""
    malformed = [
        app_client.post(
            "/audit/logs", json={**VALID_EVENT, "user_id": "u-1"}, headers=AUTH
        ),
        app_client.post("/audit/logs", json={"action": "x"}, headers=AUTH),
        app_client.post(
            "/audit/logs",
            json={**VALID_EVENT, "performed_at": "2026-10-05T12:34:56"},
            headers=AUTH,
        ),
        app_client.post(
            "/audit/logs",
            content=b"not json",
            headers={**AUTH, "Content-Type": "application/json"},
        ),
        app_client.post(
            "/audit/logs",
            content=b"[]",
            headers={**AUTH, "Content-Type": "application/json"},
        ),
        app_client.get("/audit/logs", params={"skip": -1}, headers=AUTH),
        app_client.get("/audit/logs", params={"limit": 0}, headers=AUTH),
    ]

    assert [response.status_code for response in malformed] == [400] * len(malformed)
