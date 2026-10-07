"""`MongoAuditLogRepository` contra un MongoDB de verdad.

Los unitarios afirman el mapeo rama a rama sobre excepciones fabricadas; aquí
se afirma lo que hace el servidor: que el `_id` es un `ObjectId` de verdad, que
las fechas se guardan como BSON `Date`, y que el índice único de §6.3 rechaza
la identidad repetida y ese rechazo sale como señal de replay (SPEC §5.3 y
§6.2).
"""

from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId
from pymongo import AsyncMongoClient

from app.domain.models import CreateAuditLogRequest
from app.errors import AuditStorageError
from app.repositories.mongo_audit_log_repository import MongoAuditLogRepository
from app.repositories.mongodb import ensure_indexes
from app.repositories.protocol import ReplayDetected

PERFORMED_AT = datetime(2026, 10, 5, 12, 34, 56, 789000, tzinfo=UTC)
CHECKSUM = "9f86d081884c7d659a2feaa0c55ad015"
STORAGE_DETAIL = "MongoDB is unavailable."


def make_request(**overrides: object) -> CreateAuditLogRequest:
    """Petición válida, con lo que pida el test cambiado."""
    values: dict[str, object] = {
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
        "performed_at": PERFORMED_AT,
        "details": {"page_count": 12},
    }
    values.update(overrides)
    return CreateAuditLogRequest(**values)


async def test_insert_writes_an_object_id_and_bson_dates(
    clean_collection: object,
) -> None:
    """§6.2 comprobado en el almacén y no en nuestra intención: si `_id`
    guardara un string o las fechas un `str`, el índice de §6.3 ni se crearía."""
    repository = MongoAuditLogRepository(clean_collection)

    log = await repository.insert(make_request())

    document = await clean_collection.find_one({"_id": ObjectId(log.id)})
    assert document is not None
    assert isinstance(document["_id"], ObjectId)
    assert str(document["_id"]) == log.id
    assert isinstance(document["performed_at"], datetime)
    assert isinstance(document["received_at"], datetime)
    # PyMongo devuelve fechas *naive* interpretadas en UTC (tz_aware=False):
    # el instante es el mismo, la zona horaria la añade `to_audit_log`.
    assert document["performed_at"] == PERFORMED_AT.replace(tzinfo=None)
    assert document["details"] == {"page_count": 12}


async def test_insert_stores_an_empty_object_when_details_are_absent(
    clean_collection: object,
) -> None:
    """SPEC §6.2: en la colección no debe aparecer `null`, ni siquiera
    transitoriamente."""
    repository = MongoAuditLogRepository(clean_collection)

    log = await repository.insert(make_request(details=None))

    document = await clean_collection.find_one({"_id": ObjectId(log.id)})
    assert document is not None
    assert document["details"] == {}


async def test_insert_stamps_received_at_close_to_now(
    clean_collection: object,
) -> None:
    """`received_at` del servidor, no del evento: una petición con
    `performed_at` viejo no debe heredar esa antigüedad."""
    repository = MongoAuditLogRepository(clean_collection)

    log = await repository.insert(make_request())

    assert abs((datetime.now(UTC) - log.received_at).total_seconds()) < 60


async def test_the_second_identical_event_signals_a_replay(
    clean_collection: object,
) -> None:
    """Barrera 2 de §5.3 contra el servidor: sin el índice único este test
    insertaría dos documentos en vez de rechazar el segundo."""
    await ensure_indexes(clean_collection, retention_days=0)
    repository = MongoAuditLogRepository(clean_collection)
    first = await repository.insert(make_request())

    with pytest.raises(ReplayDetected):
        await repository.insert(make_request())

    stored_count = await clean_collection.count_documents({})
    again = await repository.find_replay(
        action="pdf.extract",
        entity_type="document",
        checksum=CHECKSUM,
        performed_at=PERFORMED_AT,
    )

    assert stored_count == 1
    assert again is not None
    assert again.id == first.id


async def test_find_replay_matches_the_exact_identity(clean_collection: object) -> None:
    """Identidad exacta de §6.3: cambia un campo y no hay replay, porque dos
    extracciones del mismo documento en momentos distintos son dos eventos."""
    repository = MongoAuditLogRepository(clean_collection)
    stored = await repository.insert(make_request())
    identity = {
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
    }

    found = await repository.find_replay(**identity, performed_at=PERFORMED_AT)
    wrong_moment = await repository.find_replay(
        **identity, performed_at=PERFORMED_AT + timedelta(seconds=1)
    )
    wrong_checksum = await repository.find_replay(
        **{**identity, "checksum": "otro"},
        performed_at=PERFORMED_AT,
    )

    assert found is not None
    assert found.id == stored.id
    assert found.performed_at == stored.performed_at
    assert wrong_moment is None
    assert wrong_checksum is None


async def test_a_connection_failure_is_reported_as_a_storage_error() -> None:
    """SPEC §6.4 con un fallo real de red: el driver lanza
    `ServerSelectionTimeoutError`, y eso tiene que salir como `503` con nuestro
    texto y sin el `host:port` del intento. Este test no necesita Mongo
    levantado, así que también corre cuando el resto de integración se omite."""
    client = AsyncMongoClient("mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=100")
    repository = MongoAuditLogRepository(
        client.get_database("pdf_extractext_audit_test").get_collection("audit_logs")
    )
    try:
        with pytest.raises(AuditStorageError) as failure:
            await repository.insert(make_request())
    finally:
        await client.close()

    assert failure.value.detail == STORAGE_DETAIL
