"""Pruebas del listado por checksum con MongoDB real."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import create_app
from tests.integration.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}

BASE_TIME = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
FIRST_ID = "000000000000000000000001"
SECOND_ID = "000000000000000000000002"
THIRD_ID = "000000000000000000000003"

WANTED = "9f86d081884c7d659a2feaa0c55ad015"
OTHER = "otro-checksum"

SEVEN_FIELDS = {
    "_id",
    "action",
    "entity_type",
    "checksum",
    "details",
    "performed_at",
    "received_at",
}


def make_document(
    *, id_value: str, checksum: str, performed_at: datetime
) -> dict[str, object]:
    """Documento de §6.2 con ids y marcas de tiempo controlados por el test.

    Args:
        id_value: Identificador del documento.
        checksum: Valor que identifica el contenido.
        performed_at: Fecha y hora en que ocurrió el evento.

    Returns:
        El objeto creado para la prueba.
    """
    return {
        "_id": id_value,
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": checksum,
        "details": {"page_count": 12},
        "performed_at": performed_at,
        "received_at": performed_at + timedelta(seconds=1),
    }


async def seed(clean_collection: object, *documents: dict[str, object]) -> None:
    """Escribir los documentos directamente en la colección de pruebas.

    Args:
        clean_collection: Colección de prueba vacía.
        *documents: Argumentos adicionales.

    Returns:
        No retorna valor.
    """
    if documents:
        await clean_collection.insert_many(list(documents))


def get_by_checksum(checksum: str, **params: object):
    """Pide los registros de un checksum a la API.

    Args:
        checksum: Valor que identifica el contenido.
        **params: Argumentos adicionales.

    Returns:
        La respuesta de la API.
    """
    with TestClient(create_app()) as client:
        return client.get(
            f"/audit/logs/checksum/{checksum}", params=params, headers=AUTH
        )


async def test_returns_a_top_level_array_with_only_the_matching_checksum(
    deployed: None, clean_collection: object
) -> None:
    """Array de primer nivel con los 7 campos, filtrado **sólo** por el checksum del
    path — los de otro checksum no aparecen.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    await seed(
        clean_collection,
        make_document(id_value=FIRST_ID, checksum=WANTED, performed_at=BASE_TIME),
        make_document(
            id_value=SECOND_ID,
            checksum=OTHER,
            performed_at=BASE_TIME + timedelta(hours=1),
        ),
    )

    response = get_by_checksum(WANTED)

    body = response.json()
    assert response.status_code == 200
    assert isinstance(body, list)
    assert len(body) == 1
    assert set(body[0]) == SEVEN_FIELDS
    assert all(value is not None for value in body[0].values())
    assert body[0]["checksum"] == WANTED
    assert body[0]["_id"] == FIRST_ID
    assert len(body[0]["_id"]) == 24
    assert body[0]["performed_at"].endswith("Z")
    assert body[0]["received_at"].endswith("Z")


async def test_orders_by_performed_at_desc_with_a_stable_id_tiebreak(
    deployed: None, clean_collection: object
) -> None:
    """`performed_at desc` con desempate `_id desc` entre dos eventos del mismo
    checksum, y el mismo orden en dos llamadas idénticas.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    await seed(
        clean_collection,
        make_document(id_value=FIRST_ID, checksum=WANTED, performed_at=BASE_TIME),
        make_document(
            id_value=SECOND_ID,
            checksum=WANTED,
            performed_at=BASE_TIME + timedelta(hours=1),
        ),
        make_document(
            id_value=THIRD_ID,
            checksum=WANTED,
            performed_at=BASE_TIME + timedelta(hours=1),
        ),
    )

    first_call = get_by_checksum(WANTED)
    second_call = get_by_checksum(WANTED)

    expected_ids = [THIRD_ID, SECOND_ID, FIRST_ID]
    assert first_call.status_code == 200
    assert [item["_id"] for item in first_call.json()] == expected_ids
    assert [item["_id"] for item in second_call.json()] == expected_ids


async def test_no_matches_returns_an_empty_array(
    deployed: None, clean_collection: object
) -> None:
    """`client_test.go:170`: un checksum sin resultados es `200 []`, **nunca** un `404`.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    response = get_by_checksum("checksum-inexistente")

    assert response.status_code == 200
    assert response.json() == []


async def test_the_listing_does_not_paginate_even_if_it_receives_skip_and_limit(
    deployed: None, clean_collection: object
) -> None:
    """D12: el cliente Go no envía paginación por checksum, así que el cursor no lleva
    `.limit()`.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    await seed(
        clean_collection,
        make_document(id_value=FIRST_ID, checksum=WANTED, performed_at=BASE_TIME),
        make_document(
            id_value=SECOND_ID,
            checksum=WANTED,
            performed_at=BASE_TIME + timedelta(hours=1),
        ),
        make_document(
            id_value=THIRD_ID,
            checksum=WANTED,
            performed_at=BASE_TIME + timedelta(hours=2),
        ),
    )

    response = get_by_checksum(WANTED, limit=1, skip=5)

    assert response.status_code == 200
    assert len(response.json()) == 3


async def test_the_route_without_a_checksum_is_404_not_500(
    deployed: None, clean_collection: object
) -> None:
    """El path sin valor no casa con `{checksum}`: `404 NOT_FOUND` traducido a problem
    details, no un `500` del catch-all (AC del plan).

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    with TestClient(create_app()) as client:
        response = client.get("/audit/logs/checksum/", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_listing_by_checksum_does_not_register_an_audit_event(
    deployed: None, clean_collection: object
) -> None:
    """AUDA no se autoaudita: leer no escribe nada en la colección.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    await seed(
        clean_collection,
        make_document(id_value=FIRST_ID, checksum=WANTED, performed_at=BASE_TIME),
    )

    response = get_by_checksum(WANTED)

    assert response.status_code == 200
    assert await clean_collection.count_documents({}) == 1
