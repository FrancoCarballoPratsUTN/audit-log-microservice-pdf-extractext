"""`GET /audit/logs?skip&limit` contra MongoDB real.

Los unit de `tests/unit/api/routers/test_audit_logs_router.py` fijan la
traducción de Capa 1 (array, campos, validación) con un servicio de juguete;
aquí se prueba lo que sólo se ve con la Capa 3 detrás: que el orden sale del
índice compuesto `(performed_at desc, _id desc)` de SPEC §6.3, que dos
eventos con el mismo `performed_at` desempatan de forma estable por `_id`, y
que el `GET` **no** registra evento de auditoría — AUDA no se autoaudita.

La siembra es directa sobre `clean_collection` con `_id` hex de 24 caracteres
escritos a mano: el desempate por `_id` sólo se puede afirmar si los ids son
conocidos, y los `ObjectId` dependen del orden en que Mongo los asigna.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.integration.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}

BASE_TIME = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
FIRST_ID = "000000000000000000000001"
SECOND_ID = "000000000000000000000002"
THIRD_ID = "000000000000000000000003"

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


def get_list(**params: object):
    with TestClient(create_app()) as client:
        return client.get("/audit/logs", params=params, headers=AUTH)


async def test_returns_a_top_level_array_with_the_seven_fields_and_no_nulls(
    deployed: None, clean_collection: object
) -> None:
    """SPEC §2.4: array de primer nivel y exactamente los 7 campos de
    `models.AuditLog`, sin nulos y con fechas RFC 3339 que parsea `time.Time`."""
    await seed(
        clean_collection,
        make_document(
            id_value=FIRST_ID,
            checksum="9f86d081884c7d659a2feaa0c55ad015",
            performed_at=BASE_TIME,
        ),
    )

    response = get_list()

    body = response.json()
    assert response.status_code == 200
    assert isinstance(body, list)
    assert len(body) == 1
    assert set(body[0]) == SEVEN_FIELDS
    assert all(value is not None for value in body[0].values())
    assert body[0]["_id"] == FIRST_ID
    assert len(body[0]["_id"]) == 24
    assert int(body[0]["_id"], 16) >= 0
    assert body[0]["performed_at"].endswith("Z")
    assert body[0]["received_at"].endswith("Z")
    assert (
        datetime.fromisoformat(body[0]["performed_at"].replace("Z", "+00:00")).tzinfo
        is not None
    )


async def test_orders_by_performed_at_desc_with_a_stable_id_tiebreak(
    deployed: None, clean_collection: object
) -> None:
    """SPEC §6.3: `performed_at desc` con desempate `_id desc` entre dos
    eventos simultáneos, y el mismo orden en dos llamadas idénticas."""
    await seed(
        clean_collection,
        make_document(
            id_value=FIRST_ID,
            checksum="checksum-1",
            performed_at=BASE_TIME,
        ),
        make_document(
            id_value=SECOND_ID,
            checksum="checksum-2",
            performed_at=BASE_TIME + timedelta(hours=1),
        ),
        make_document(
            id_value=THIRD_ID,
            checksum="checksum-3",
            performed_at=BASE_TIME + timedelta(hours=1),
        ),
    )

    first_call = get_list()
    second_call = get_list()

    expected_ids = [THIRD_ID, SECOND_ID, FIRST_ID]
    assert first_call.status_code == 200
    assert [item["_id"] for item in first_call.json()] == expected_ids
    assert [item["_id"] for item in second_call.json()] == expected_ids


async def test_skip_and_limit_page_the_ordered_collection(
    deployed: None, clean_collection: object
) -> None:
    """SPEC §8.1 / `client_test.go:118-123`: ambos valores se propagan y
    recortan la colección **ya ordenada**, no la aleatoria."""
    await seed(
        clean_collection,
        make_document(
            id_value=FIRST_ID,
            checksum="checksum-1",
            performed_at=BASE_TIME,
        ),
        make_document(
            id_value=SECOND_ID,
            checksum="checksum-2",
            performed_at=BASE_TIME + timedelta(hours=1),
        ),
        make_document(
            id_value=THIRD_ID,
            checksum="checksum-3",
            performed_at=BASE_TIME + timedelta(hours=2),
        ),
    )

    response = get_list(skip=1, limit=1)

    body = response.json()
    assert response.status_code == 200
    assert isinstance(body, list)
    assert [item["_id"] for item in body] == [SECOND_ID]


async def test_no_results_returns_an_empty_array(
    deployed: None, clean_collection: object
) -> None:
    """Colección vacía ⇒ `200 []`. Un listado sin resultados nunca es un
    `404` (SPEC §4.5)."""
    response = get_list()

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "params",
    [{"skip": -1}, {"skip": 10001}, {"limit": 0}, {"limit": 101}],
)
async def test_out_of_range_pagination_is_rejected_with_400(
    deployed: None, clean_collection: object, params: dict[str, int]
) -> None:
    """SPEC §5.2 y D16: el rango se rechaza con `400 VALIDATION_ERROR`,
    nunca se recorta en silencio ni se pagina igual."""
    response = get_list(**params)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_the_get_does_not_register_an_audit_event(
    deployed: None, clean_collection: object
) -> None:
    """AUDA no se autoaudita: leer no escribe nada en la colección."""
    await seed(
        clean_collection,
        make_document(
            id_value=FIRST_ID,
            checksum="checksum-1",
            performed_at=BASE_TIME,
        ),
        make_document(
            id_value=SECOND_ID,
            checksum="checksum-2",
            performed_at=BASE_TIME + timedelta(hours=1),
        ),
    )

    response = get_list()

    assert response.status_code == 200
    assert await clean_collection.count_documents({}) == 2
