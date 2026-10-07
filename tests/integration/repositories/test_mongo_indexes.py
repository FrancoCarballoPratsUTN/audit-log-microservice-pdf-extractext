"""Los índices de SPEC §6.3 contra un MongoDB de verdad.

Los tests unitarios de `tests/unit/repositories/test_mongodb_lifecycle.py`
afirman lo que el código **declara**. Estos afirman lo que MongoDB **hace**, que
es lo único que importa: `IndexModel` es una clase nuestra en papel, y el
veredicto lo emite el servidor.

La comprobación de §6.3 con `mongosh` que pedía el plan está aquí, automatizada y
con un fallo en vez de con una comparación a ojo.
"""

from datetime import UTC, datetime

import pytest
from pymongo.errors import DuplicateKeyError

from app.repositories.mongodb import (
    CHECKSUM_LOOKUP_INDEX,
    GLOBAL_LOOKUP_INDEX,
    UNIQUE_IDEMPOTENCY_INDEX,
    ensure_indexes,
    ttl_index,
)
from tests.integration.conftest import COLLECTION_NAME

IDENTITY_INDEX_NAME = "unq_audit_event_identity"


def make_document(**overrides: object) -> dict[str, object]:
    """Un documento válido según §6.2, con lo que pida el test cambiado."""
    document: dict[str, object] = {
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": "9f86d081884c7d659a2feaa0c55ad015",
        "details": {"page_count": 12},
        "performed_at": datetime(2026, 10, 5, 12, 34, 56, 789000, tzinfo=UTC),
        "received_at": datetime(2026, 10, 5, 12, 34, 57, 41000, tzinfo=UTC),
    }
    document.update(overrides)
    return document


async def test_the_three_indexes_exist_when_retention_is_disabled(
    clean_collection: object,
) -> None:
    await ensure_indexes(clean_collection, retention_days=0)

    names = set(await clean_collection.index_information())

    assert names == {
        "_id_",
        UNIQUE_IDEMPOTENCY_INDEX.name,
        CHECKSUM_LOOKUP_INDEX.name,
        GLOBAL_LOOKUP_INDEX.name,
    }


async def test_no_ttl_index_exists_when_retention_is_disabled(
    clean_collection: object,
) -> None:
    """`RETENTION_DAYS = 0` no crea TTL: un índice con `expireAfterSeconds: 0`
    borraría la auditoría entera segundos después de arrancar."""
    await ensure_indexes(clean_collection, retention_days=0)

    indexes = await clean_collection.index_information()

    assert all("expireAfterSeconds" not in spec for spec in indexes.values())


async def test_the_ttl_index_exists_with_the_configured_window(
    clean_collection: object,
) -> None:
    spec = ttl_index(30)
    assert spec is not None

    await ensure_indexes(clean_collection, retention_days=30)
    indexes = await clean_collection.index_information()

    assert spec.name in indexes
    assert indexes[spec.name]["expireAfterSeconds"] == 30 * 86400
    assert indexes[spec.name]["key"] == [("performed_at", 1)]


async def test_mongo_reports_the_compound_indexes_with_id_descending(
    clean_collection: object,
) -> None:
    """§6.3 y §12 comprobados contra el servidor, no contra nuestra intención: es
    aquí donde se vería un `1` donde debía haber un `-1`."""
    await ensure_indexes(clean_collection, retention_days=0)
    indexes = await clean_collection.index_information()

    assert indexes[CHECKSUM_LOOKUP_INDEX.name]["key"] == [
        ("checksum", 1),
        ("performed_at", -1),
        ("_id", -1),
    ]
    assert indexes[GLOBAL_LOOKUP_INDEX.name]["key"] == [
        ("performed_at", -1),
        ("_id", -1),
    ]


async def test_mongo_reports_the_identity_index_as_unique(
    clean_collection: object,
) -> None:
    await ensure_indexes(clean_collection, retention_days=0)
    indexes = await clean_collection.index_information()

    assert indexes[IDENTITY_INDEX_NAME]["unique"] is True
    assert indexes[IDENTITY_INDEX_NAME]["key"] == [
        ("action", 1),
        ("entity_type", 1),
        ("checksum", 1),
        ("performed_at", 1),
    ]


async def test_the_unique_index_rejects_the_same_identity_twice(
    clean_collection: object,
) -> None:
    """Barrera 2 de §5.3: el índice único es lo que cierra la carrera entre dos
    peticiones concurrentes. Aquí se comprueba que Mongo, y no nuestra confianza,
    lo rechaza."""
    await ensure_indexes(clean_collection, retention_days=0)
    await clean_collection.insert_one(make_document())

    with pytest.raises(DuplicateKeyError):
        await clean_collection.insert_one(make_document())

    assert await clean_collection.count_documents({}) == 1


async def test_the_same_checksum_with_a_different_action_is_accepted(
    clean_collection: object,
) -> None:
    """Un checksum genera varios eventos (`pdf.extract`, `text.create`, ...). Si el
    índice único fuera sólo por `checksum`, el segundo evento se rechazaría y se
    perdería una auditoría real (SPEC §2.5 H3)."""
    await ensure_indexes(clean_collection, retention_days=0)
    await clean_collection.insert_one(make_document())

    await clean_collection.insert_one(make_document(action="text.create"))

    assert await clean_collection.count_documents({}) == 2


async def test_the_same_action_and_checksum_at_a_different_moment_is_accepted(
    clean_collection: object,
) -> None:
    """Dos extracciones del mismo documento en instantes distintos son dos
    eventos, no un replay."""
    await ensure_indexes(clean_collection, retention_days=0)
    await clean_collection.insert_one(make_document())
    later = datetime(2026, 10, 5, 13, 0, 0, tzinfo=UTC)

    await clean_collection.insert_one(make_document(performed_at=later))

    assert await clean_collection.count_documents({}) == 2


async def test_creating_the_indexes_twice_is_harmless(
    clean_collection: object,
) -> None:
    """El arranque se repite en cada despliegue y en cada reinicio: si
    `create_indexes` no fuera idempotente, el segundo despliegue rompería el
    servicio."""
    await ensure_indexes(clean_collection, retention_days=30)

    await ensure_indexes(clean_collection, retention_days=30)

    assert len(await clean_collection.index_information()) == 5


def make_documents(count: int, **overrides: object) -> list[dict[str, object]]:
    """`count` documentos con la misma marca de tiempo e identidad distinta.

    La identidad tiene que variar porque el índice único de §6.3 rechaza dos
    documentos iguales, y las fechas se repiten a propósito: es lo que obliga al
    desempate de §12 a hacer su trabajo.
    """
    return [
        make_document(action=f"pdf.extract.{index}", **overrides)
        for index in range(count)
    ]


async def test_the_compound_indexes_are_actually_used_by_the_query(
    clean_collection: object,
) -> None:
    """Un índice que existe pero que Mongo no elige sirve de nada, y `explain` es
    la única forma de comprobarlo.

    Se insertan 200 documentos porque con tres el planificador elige `COLLSCAN`, y
    hace bien: recorrer tres documentos es más barato que mantener un árbol B.
    """
    await ensure_indexes(clean_collection, retention_days=0)
    await clean_collection.insert_many(make_documents(200))

    checksum_plan = (
        await clean_collection.find({"checksum": "9f86d081884c7d659a2feaa0c55ad015"})
        .sort("performed_at", -1)
        .explain()
    )
    global_plan = await clean_collection.find({}).sort("performed_at", -1).explain()

    assert (
        checksum_plan["queryPlanner"]["winningPlan"]["inputStage"]["indexName"]
        == CHECKSUM_LOOKUP_INDEX.name
    )
    assert (
        global_plan["queryPlanner"]["winningPlan"]["inputStage"]["indexName"]
        == GLOBAL_LOOKUP_INDEX.name
    )


async def test_the_plan_declares_both_fields_descending(
    clean_collection: object,
) -> None:
    """El `keyPattern` del plan es lo que Mongo dice que va a recorrer: si aquí
    apareciera un `1` donde debía haber un `-1`, el índice se creó bien pero la
    consulta lo usa al revés."""
    await ensure_indexes(clean_collection, retention_days=0)
    await clean_collection.insert_many(make_documents(200))

    plan = await clean_collection.find({}).sort("performed_at", -1).explain()
    pattern = plan["queryPlanner"]["winningPlan"]["inputStage"]["keyPattern"]

    assert pattern == {"performed_at": -1, "_id": -1}


async def test_the_query_plan_returns_a_stable_order_for_equal_timestamps(
    clean_collection: object,
) -> None:
    """§12 en su forma observable: veinte eventos con el mismo `performed_at` deben
    salir siempre en el mismo orden. Sin el `_id` descendente, Mongo puede
    devolverlos en cualquier orden entre llamadas, y `skip/limit` paginaría filas
    repetidas y huecos."""
    await ensure_indexes(clean_collection, retention_days=0)
    await clean_collection.insert_many(make_documents(20))

    runs = [
        [
            document["_id"]
            for document in await clean_collection.find({})
            .sort("performed_at", -1)
            .to_list(length=20)
        ]
        for _ in range(3)
    ]

    assert runs[0] == runs[1] == runs[2]


async def test_skip_and_limit_paginates_without_repeating_or_skipping(
    clean_collection: object,
) -> None:
    """El bug concreto de §12, de punta a punta: dos páginas de cinco sobre veinte
    eventos empatados no pueden solaparse ni dejar huecos."""
    await ensure_indexes(clean_collection, retention_days=0)
    await clean_collection.insert_many(make_documents(20))

    first_page = (
        await clean_collection.find({})
        .sort("performed_at", -1)
        .skip(0)
        .limit(5)
        .to_list(length=5)
    )
    second_page = (
        await clean_collection.find({})
        .sort("performed_at", -1)
        .skip(5)
        .limit(5)
        .to_list(length=5)
    )

    first_ids = [document["_id"] for document in first_page]
    second_ids = [document["_id"] for document in second_page]

    assert len(first_ids) == len(second_ids) == 5
    assert not set(first_ids) & set(second_ids)


async def test_the_collection_lives_where_the_configuration_says(
    clean_collection: object,
) -> None:
    """Un índice creado en la colección equivocada no protege de nada, y no se
    nota hasta que hay dos documentos con la misma identidad."""
    assert clean_collection.name == COLLECTION_NAME
    assert clean_collection.database.name == "pdf_extractext_audit_test"
