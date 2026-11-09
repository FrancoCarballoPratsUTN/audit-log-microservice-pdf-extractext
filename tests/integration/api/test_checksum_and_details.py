"""Pruebas del checksum y de los detalles."""

from tests.integration.api.helpers import (
    AUTH,
    VALID_EVENT,
    app_client,
)


async def test_an_arbitrary_checksum_is_accepted_and_the_location_is_escaped(
    deployed: None, clean_collection: object
) -> None:
    """El checksum es opaco: no-hex, con guiones, mayúsculas, e incluso caracteres de
    URL.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    from urllib.parse import quote

    checksum = 'Mi-/checksum?&="raro" #mañana'
    event = {**VALID_EVENT, "checksum": checksum}

    with app_client() as client:
        response = client.post("/audit/logs", json=event, headers=AUTH)

    assert response.status_code == 201
    assert response.headers["Location"] == (
        "/audit/logs/checksum/" + quote(checksum, safe="")
    )
    document = await clean_collection.find_one({"checksum": checksum})
    assert document is not None
    assert document["checksum"] == checksum


async def test_absent_details_are_stored_as_an_empty_object(
    deployed: None, clean_collection: object
) -> None:
    """`text.delete` omite `details` (`omitempty`); el guardado es `{}`, nunca `null`.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    payload = {k: v for k, v in VALID_EVENT.items() if k != "details"}

    with app_client() as client:
        response = client.post("/audit/logs", json=payload, headers=AUTH)

    assert response.status_code == 201
    assert response.json()["details"] == {}
    document = await clean_collection.find_one({"checksum": VALID_EVENT["checksum"]})
    assert document["details"] == {}


async def test_nested_details_are_stored_verbatim(
    deployed: None, clean_collection: object
) -> None:
    """`details` es `Any`: las extensiones del emisor llegan intactas, sin aplanarlas ni
    recortarlas.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    details = {
        "user": {"id": "u-1", "roles": ["admin", None]},
        "items": [1, "dos", {"x": True}],
    }
    event = {**VALID_EVENT, "details": details}

    with app_client() as client:
        response = client.post("/audit/logs", json=event, headers=AUTH)

    assert response.status_code == 201
    assert response.json()["details"] == details
    document = await clean_collection.find_one({"checksum": VALID_EVENT["checksum"]})
    assert document["details"] == details
