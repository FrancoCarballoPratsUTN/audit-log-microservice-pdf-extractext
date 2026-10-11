"""`GET /audit/logs/checksum/{checksum}` contra MongoDB real.

El path lo fija `client_test.go:156` del orquestador y el caso sin resultados
está en `client_test.go:170`. Los unit de
`tests/unit/api/routers/test_audit_logs_router.py` fijan la traducción de
Capa 1 con un servicio de juguete; aquí se prueba lo que sólo se ve con la
Capa 3 detrás: que el filtro sale del índice compuesto
`(checksum, performed_at desc, _id desc)` de SPEC §6.3, que dos eventos con el
mismo `performed_at` desempatan de forma estable por `_id`, y que el listado
por checksum **no** pagina (D12).

La siembra es directa sobre `clean_collection` con `_id` hex de 24 caracteres
escritos a mano, como en `test_list_audit_logs.py`: el desempate por `_id` sólo
se puede afirmar si los ids son conocidos.
"""

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
    """Documento de §6.2 con ids y marcas de tiempo controlados por el test."""
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
    """Escribir los documentos directamente en la colección de pruebas."""
    if documents:
        await clean_collection.insert_many(list(documents))


def get_by_checksum(checksum: str, **params: object):
    with TestClient(create_app()) as client:
        return client.get(
            f"/audit/logs/checksum/{checksum}", params=params, headers=AUTH
        )


async def test_returns_a_top_level_array_with_only_the_matching_checksum(
    deployed: None, clean_collection: object
) -> None:
    """SPEC §8.1: array de primer nivel con los 7 campos, filtrado **sólo** por
    el checksum del path — los de otro checksum no aparecen."""
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
    """SPEC §8.1 / §6.3: `performed_at desc` con desempate `_id desc` entre dos
    eventos del mismo checksum, y el mismo orden en dos llamadas idénticas."""
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
    """`client_test.go:170`: un checksum sin resultados es `200 []`, **nunca**
    un `404` (SPEC §4.5)."""
    response = get_by_checksum("checksum-inexistente")

    assert response.status_code == 200
    assert response.json() == []


async def test_the_listing_does_not_paginate_even_if_it_receives_skip_and_limit(
    deployed: None, clean_collection: object
) -> None:
    """D12: el cliente Go no envía paginación por checksum, así que el cursor no
    lleva `.limit()`. Si un cliente enviara `limit`, se ignora — el endpoint no
    pagina, y recortar mentiría sobre el total."""
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
    """El path sin valor no casa con `{checksum}`: `404 NOT_FOUND` traducido a
    problem details, no un `500` del catch-all (AC del plan)."""
    with TestClient(create_app()) as client:
        response = client.get("/audit/logs/checksum/", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_listing_by_checksum_does_not_register_an_audit_event(
    deployed: None, clean_collection: object
) -> None:
    """AUDA no se autoaudita: leer no escribe nada en la colección."""
    await seed(
        clean_collection,
        make_document(id_value=FIRST_ID, checksum=WANTED, performed_at=BASE_TIME),
    )

    response = get_by_checksum(WANTED)

    assert response.status_code == 200
    assert await clean_collection.count_documents({}) == 1
