"""El primer camino vertical completo: `POST /audit/logs` contra MongoDB real.

Los unit de `tests/unit/api/routers/test_audit_logs_router.py` aíslan la Capa 1
con un servicio de juguete; aquí se prueba el mismo cable con la Capa 3 real
detrás, y lo que sólo se puede afirmar desde fuera de la app: que **el documento
existe en Mongo**, que el replay deja exactamente un documento, y que un `413`
no escribe nada. Pedir la colección real (`clean_collection`) es la forma de
no creerle al router sobre lo que pasó por debajo.

El `clean_collection` se usa asíncrono y el `TestClient` corre su propio loop:
los clientes son distintos pero la base es la misma, así que se puede posting
con uno y leer con el otro.
"""

from urllib.parse import quote

from fastapi.testclient import TestClient

from app.main import create_app
from tests.integration.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}

VALID_EVENT = {
    "action": "pdf.extract",
    "entity_type": "document",
    "checksum": "9f86d081884c7d659a2feaa0c55ad015",
    "details": {"page_count": 12},
    "performed_at": "2026-10-05T12:34:56.789Z",
}


async def test_valid_event_gets_201_with_location_and_the_seven_fields(
    deployed: None, clean_collection: object
) -> None:
    """SPEC §4.4 paso 9: `201` + `Location: /audit/logs/checksum/<escaped>` +
    documento completo."""
    with TestClient(create_app()) as client:
        response = client.post("/audit/logs", json=VALID_EVENT, headers=AUTH)

    body = response.json()
    assert response.status_code == 201
    assert response.headers["Location"] == "/audit/logs/checksum/" + quote(
        VALID_EVENT["checksum"], safe=""
    )
    assert len(body["_id"]) == 24 and int(body["_id"], 16) >= 0
    assert body["action"] == VALID_EVENT["action"]
    assert body["entity_type"] == VALID_EVENT["entity_type"]
    assert body["checksum"] == VALID_EVENT["checksum"]
    assert body["details"] == {"page_count": 12}
    assert body["performed_at"] == VALID_EVENT["performed_at"]
    assert body["received_at"].endswith("Z")
    assert body["idempotent_replay"] is False


async def test_the_document_really_landed_in_mongo(
    deployed: None, clean_collection: object
) -> None:
    """El `201` no es una promesa: el documento está en la colección correcta."""
    with TestClient(create_app()) as client:
        response = client.post("/audit/logs", json=VALID_EVENT, headers=AUTH)

    assert response.status_code == 201
    document = await clean_collection.find_one({"checksum": VALID_EVENT["checksum"]})
    assert document is not None
    assert document["action"] == VALID_EVENT["action"]
    assert document["entity_type"] == VALID_EVENT["entity_type"]
    assert document["details"] == {"page_count": 12}
    assert document["performed_at"] is not None
    assert document["received_at"] is not None


async def test_an_identical_event_is_a_replay_and_leaves_one_document(
    deployed: None, clean_collection: object
) -> None:
    """El reintento del orquestador (SPEC §5.3) responde `200` con el log
    original, nunca inserta un segundo documento."""
    with TestClient(create_app()) as client:
        first = client.post("/audit/logs", json=VALID_EVENT, headers=AUTH)
        second = client.post("/audit/logs", json=VALID_EVENT, headers=AUTH)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["X-Idempotent-Replay"] == "true"
    assert second.headers["Location"] == first.headers["Location"]
    body = second.json()
    assert body["idempotent_replay"] is True
    assert body["_id"] == first.json()["_id"]

    documents = await clean_collection.find({}).to_list(None)
    assert len(documents) == 1


def test_missing_required_field_is_400_validation_error(deployed: None) -> None:
    payload = {k: v for k, v in VALID_EVENT.items() if k != "action"}

    with TestClient(create_app()) as client:
        response = client.post("/audit/logs", json=payload, headers=AUTH)

    assert response.status_code == 400
    body = response.json()
    assert body["type"] == "/problems/validation_error"
    assert body["status"] == 400
    assert body["code"] == "VALIDATION_ERROR"
    assert body["instance"] == "/audit/logs"


def test_unknown_top_level_key_is_400(deployed: None) -> None:
    """`extra="forbid"` (SPEC §3.4): un 201 que descarta `user_id` en silencio es
    el peor fallo posible en una auditoría."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/audit/logs", json={**VALID_EVENT, "user_id": "u-1"}, headers=AUTH
        )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_performed_at_without_offset_is_400(deployed: None) -> None:
    """`AwareDatetime`: una fecha naive no localiza el evento, se rechaza."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/audit/logs",
            json={**VALID_EVENT, "performed_at": "2026-10-05T12:34:56"},
            headers=AUTH,
        )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_details_over_the_limit_is_413_and_nothing_is_written(
    deployed: None, clean_collection: object
) -> None:
    """SPEC §4.4 paso 6: el límite de `details` se comprueba antes de la Capa 2."""
    event = {**VALID_EVENT, "details": {"blob": "x" * 70000}}

    with TestClient(create_app()) as client:
        response = client.post("/audit/logs", json=event, headers=AUTH)

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert await clean_collection.count_documents({}) == 0


async def test_an_arbitrary_checksum_is_accepted_and_the_location_is_escaped(
    deployed: None, clean_collection: object
) -> None:
    """El checksum es opaco (SPEC §5.2): no-hex, con guiones, mayúsculas, e
    incluso caracteres de URL. Se acepta, se persiste tal cual, y el `Location`
    escapa todo carácter con `quote(..., safe="")`."""
    checksum = 'Mi-/checksum?&="raro" #mañana'
    event = {**VALID_EVENT, "checksum": checksum}

    with TestClient(create_app()) as client:
        response = client.post("/audit/logs", json=event, headers=AUTH)

    assert response.status_code == 201
    assert response.headers["Location"] == "/audit/logs/checksum/" + quote(
        checksum, safe=""
    )
    document = await clean_collection.find_one({"checksum": checksum})
    assert document is not None
    assert document["checksum"] == checksum


async def test_absent_details_are_stored_as_an_empty_object(
    deployed: None, clean_collection: object
) -> None:
    """`text.delete` omite `details` (`omitempty`); el guardado es `{}`, nunca
    `null`."""
    payload = {k: v for k, v in VALID_EVENT.items() if k != "details"}

    with TestClient(create_app()) as client:
        response = client.post("/audit/logs", json=payload, headers=AUTH)

    assert response.status_code == 201
    assert response.json()["details"] == {}
    document = await clean_collection.find_one({"checksum": VALID_EVENT["checksum"]})
    assert document["details"] == {}


async def test_nested_details_are_stored_verbatim(
    deployed: None, clean_collection: object
) -> None:
    """`details` es `Any` (SPEC §2.5 H4): las extensiones del emisor llegan
    intactas, sin aplanarlas ni recortarlas."""
    details = {
        "user": {"id": "u-1", "roles": ["admin", None]},
        "items": [1, "dos", {"x": True}],
    }
    event = {**VALID_EVENT, "details": details}

    with TestClient(create_app()) as client:
        response = client.post("/audit/logs", json=event, headers=AUTH)

    assert response.status_code == 201
    assert response.json()["details"] == details
    document = await clean_collection.find_one({"checksum": VALID_EVENT["checksum"]})
    assert document["details"] == details
