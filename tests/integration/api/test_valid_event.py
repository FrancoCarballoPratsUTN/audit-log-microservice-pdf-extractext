"""Pruebas de un evento válido guardado en MongoDB."""

from urllib.parse import quote

from tests.integration.api.helpers import AUTH, VALID_EVENT, app_client


async def test_valid_event_gets_201_with_location_and_the_seven_fields(
    deployed: None, clean_collection: object
) -> None:
    """`201` + `Location` + documento completo.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    with app_client() as client:
        response = client.post("/audit/logs", json=VALID_EVENT, headers=AUTH)

    body = response.json()
    assert response.status_code == 201
    assert response.headers["Location"] == (
        "/audit/logs/checksum/" + quote(VALID_EVENT["checksum"], safe="")
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
    """El `201` no es una promesa: el documento está en la colección correcta.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    with app_client() as client:
        response = client.post("/audit/logs", json=VALID_EVENT, headers=AUTH)

    assert response.status_code == 201
    document = await clean_collection.find_one({"checksum": VALID_EVENT["checksum"]})
    assert document is not None
    assert document["action"] == VALID_EVENT["action"]
    assert document["entity_type"] == VALID_EVENT["entity_type"]
    assert document["details"] == {"page_count": 12}
    assert document["performed_at"] is not None
    assert document["received_at"] is not None
