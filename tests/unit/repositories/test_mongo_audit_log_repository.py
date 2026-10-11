"""`MongoAuditLogRepository` sin Mongo: el mapeo de SPEC §6.4, rama a rama.

Las excepciones se fabrican con las clases que PyMongo lanza de verdad, porque
la traducción se define sobre esas clases y no sobre nuestros inventos. Aquí se
fija qué sale de cada rama del `try`; la comprobación contra un servidor real
(índice único, `ObjectId`, fechas BSON) vive en
`tests/integration/repositories/test_mongo_audit_log_repository.py`.
"""

from datetime import UTC, datetime

import pytest
from bson import ObjectId
from pymongo.errors import DocumentTooLarge, DuplicateKeyError, PyMongoError

from app.domain.models import CreateAuditLogRequest
from app.errors import AuditStorageError, PayloadTooLargeError
from app.repositories.mongo_audit_log_repository import MongoAuditLogRepository
from app.repositories.protocol import ReplayDetected

PERFORMED_AT = datetime(2026, 10, 5, 12, 34, 56, 789000, tzinfo=UTC)
CHECKSUM = "9f86d081884c7d659a2feaa0c55ad015"


def make_request(**overrides: object) -> CreateAuditLogRequest:
    """Petición válida, con lo que pida el test cambiado."""
    values: dict[str, object] = {
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
        "performed_at": PERFORMED_AT,
    }
    values.update(overrides)
    return CreateAuditLogRequest(**values)


def make_document(**overrides: object) -> dict[str, object]:
    """Documento ya guardado, con fechas *naive* como las devuelve Mongo."""
    document: dict[str, object] = {
        "_id": ObjectId(),
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
        "details": {"page_count": 12},
        "performed_at": PERFORMED_AT.replace(tzinfo=None),
        "received_at": datetime(2026, 10, 5, 12, 34, 57, 41000),
    }
    document.update(overrides)
    return document


class RecordingCollection:
    """Colección falsa: guarda lo que recibe y lanza lo que se le ordene."""

    def __init__(
        self,
        *,
        insert_error: Exception | None = None,
        find_result: dict[str, object] | None = None,
        find_error: Exception | None = None,
        documents: list[dict[str, object]] | None = None,
    ) -> None:
        self.insert_error = insert_error
        self.find_result = find_result
        self.find_error = find_error
        self.documents = list(documents or [])
        self.inserted: list[dict[str, object]] = []
        self.queries: list[dict[str, object]] = []
        self.sorts: list[object] = []
        self.skips: list[int] = []
        self.limits: list[int] = []

    async def insert_one(self, document: dict[str, object]) -> None:
        if self.insert_error is not None:
            raise self.insert_error
        self.inserted.append(document)

    async def find_one(self, query: dict[str, object]) -> dict[str, object] | None:
        self.queries.append(query)
        if self.find_error is not None:
            raise self.find_error
        return self.find_result

    def find(self, query: dict[str, object]) -> RecordingCursor:
        self.queries.append(query)
        return RecordingCursor(self)


class RecordingCursor:
    """Cursor en memoria: registra `sort`/`skip`/`limit` y devuelve los
    documentos sin aplicarlos. Repartir esas responsabilidades es a propósito:
    el orden y el corte los ejecuta Mongo —aquí sólo se fija lo que el
    repositorio le pide, igual que `test_find_replay_queries_exactly_the_...`
    fija la consulta sin ejecutarla—, y la comprobación de que el orden real
    es el de SPEC §8.1 vive contra el servidor en
    `tests/integration/api/test_list_audit_logs.py`."""

    def __init__(self, collection: RecordingCollection) -> None:
        self._collection = collection

    def sort(self, spec: object) -> RecordingCursor:
        self._collection.sorts.append(spec)
        return self

    def skip(self, value: int) -> RecordingCursor:
        self._collection.skips.append(value)
        return self

    def limit(self, value: int) -> RecordingCursor:
        self._collection.limits.append(value)
        return self

    def __aiter__(self) -> RecordingCursor:
        self._index = 0
        return self

    async def __anext__(self) -> dict[str, object]:
        if self._collection.find_error is not None:
            raise self._collection.find_error
        if self._index >= len(self._collection.documents):
            raise StopAsyncIteration
        document = self._collection.documents[self._index]
        self._index += 1
        return document


async def test_insert_stores_the_document_and_returns_the_stored_log() -> None:
    """El registro devuelto es el que acaba en la colección: mismo `_id`, misma
    identidad y los detalles tal cual llegaron."""
    collection = RecordingCollection()
    request = make_request()

    log = await MongoAuditLogRepository(collection).insert(request)

    document = collection.inserted[0]
    assert log.id == str(document["_id"])
    assert len(log.id) == 24
    assert document["action"] == request.action
    assert document["entity_type"] == request.entity_type
    assert document["checksum"] == request.checksum
    assert document["performed_at"] == request.performed_at


async def test_insert_stamps_received_at_with_the_server_clock() -> None:
    """No es el `performed_at` del evento: es cuándo lo vimos nosotros, y de
    eso depende la ventana de retención y el orden global de §6.3."""
    collection = RecordingCollection()

    log = await MongoAuditLogRepository(collection).insert(make_request())

    assert abs((datetime.now(UTC) - log.received_at).total_seconds()) < 5
    assert log.received_at.tzinfo is not None
    assert collection.inserted[0]["received_at"] == log.received_at


async def test_insert_writes_an_empty_object_when_details_are_absent() -> None:
    """SPEC §6.2: `null` en `details` viola el esquema. La conversión ocurre
    antes de que el driver vea el documento, no después."""
    collection = RecordingCollection()

    await MongoAuditLogRepository(collection).insert(make_request(details=None))

    assert collection.inserted[0]["details"] == {}


async def test_a_duplicate_identity_signals_a_replay() -> None:
    """Barrera 2 de §5.3: el índice único habla y la traducción es una señal,
    no un `500`. Sin ella, el segundo pico de la carrera respondería con un
    error donde el Orquestador espera el `200` idempotente."""
    collection = RecordingCollection(
        insert_error=DuplicateKeyError("E11000 duplicate key error")
    )

    with pytest.raises(ReplayDetected):
        await MongoAuditLogRepository(collection).insert(make_request())


async def test_a_document_that_is_too_large_is_a_payload_error() -> None:
    """SPEC §6.4: el límite de 16 MiB de BSON es `413`, el mismo código que el
    del body de 1 MiB. Un `503` haría que el Orquestador reintentara para
    siempre un documento que nunca cabrá."""
    collection = RecordingCollection(insert_error=DocumentTooLarge("BSON too large"))

    with pytest.raises(PayloadTooLargeError):
        await MongoAuditLogRepository(collection).insert(make_request())


async def test_a_driver_failure_is_reported_as_a_storage_error() -> None:
    """SPEC §6.4: cualquier otro `PyMongoError` es `503` reintentable, con un
    `detail` nuestro y no el del driver (que trae `host:port`)."""
    collection = RecordingCollection(insert_error=PyMongoError("localhost:27017 down"))

    with pytest.raises(AuditStorageError) as failure:
        await MongoAuditLogRepository(collection).insert(make_request())

    assert "27017" not in failure.value.detail


async def test_insert_does_not_translate_a_programming_error() -> None:
    """Un `TypeError` es un bug nuestro: convertirlo en `503` haría que el
    Orquestador reintente algo que nunca se arreglará solo, y escondería el
    defecto detrás de un reintento."""
    collection = RecordingCollection(insert_error=TypeError("campo mal construido"))

    with pytest.raises(TypeError):
        await MongoAuditLogRepository(collection).insert(make_request())


async def test_find_replay_queries_exactly_the_identity_tuple() -> None:
    """Los cuatro campos de la clave única de §6.3, ni uno más ni uno menos:
    sin `performed_at` devolvería el primer evento del `action`, y sin
    `entity_type` confundiría entidades con el mismo checksum."""
    collection = RecordingCollection(find_result=None)

    await MongoAuditLogRepository(collection).find_replay(
        action="pdf.extract",
        entity_type="document",
        checksum=CHECKSUM,
        performed_at=PERFORMED_AT,
    )

    assert collection.queries[0] == {
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
        "performed_at": PERFORMED_AT,
    }


async def test_find_replay_returns_the_stored_log() -> None:
    """La Barrera 1 devuelve el registro existente, con su `_id` de Mongo."""
    document = make_document()
    collection = RecordingCollection(find_result=document)

    found = await MongoAuditLogRepository(collection).find_replay(
        action="pdf.extract",
        entity_type="document",
        checksum=CHECKSUM,
        performed_at=PERFORMED_AT,
    )

    assert found is not None
    assert found.id == str(document["_id"])
    assert found.performed_at == PERFORMED_AT
    assert found.details == document["details"]


async def test_find_replay_returns_none_when_nothing_matches() -> None:
    collection = RecordingCollection(find_result=None)

    found = await MongoAuditLogRepository(collection).find_replay(
        action="pdf.extract",
        entity_type="document",
        checksum=CHECKSUM,
        performed_at=PERFORMED_AT,
    )

    assert found is None


async def test_find_replay_reports_a_storage_failure() -> None:
    """La lectura de la Barrera 1 falla igual que la escritura: mismo `503`,
    porque quien no puede leer tampoco puede decidir si hay replay."""
    collection = RecordingCollection(find_error=PyMongoError("localhost:27017 down"))

    with pytest.raises(AuditStorageError):
        await MongoAuditLogRepository(collection).find_replay(
            action="pdf.extract",
            entity_type="document",
            checksum=CHECKSUM,
            performed_at=PERFORMED_AT,
        )


async def test_find_replay_does_not_translate_a_programming_error() -> None:
    """Mismo criterio que en `insert`: los bugs suben intactos."""
    collection = RecordingCollection(find_error=TypeError("query mal construida"))

    with pytest.raises(TypeError):
        await MongoAuditLogRepository(collection).find_replay(
            action="pdf.extract",
            entity_type="document",
            checksum=CHECKSUM,
            performed_at=PERFORMED_AT,
        )


async def test_list_sorts_by_performed_at_then_id_desc_and_pages() -> None:
    """SPEC §8.1: el listado global no filtra —son todos los eventos— y pide
    el orden exacto del índice compuesto de §6.3, con el `_id` descendente
    como desempate. Sin esa clave, dos eventos simultáneos podían paginar de
    forma distinta en dos llamadas idénticas."""
    collection = RecordingCollection(documents=[make_document()])

    await MongoAuditLogRepository(collection).list(skip=5, limit=20)

    assert collection.queries == [{}]
    assert collection.sorts == [[("performed_at", -1), ("_id", -1)]]
    assert collection.skips == [5]
    assert collection.limits == [20]


async def test_list_returns_the_page_mapped_to_domain_logs() -> None:
    """La página llega como registros de dominio: `_id` hex y fechas con zona."""
    first = make_document()
    second = make_document(checksum="otro-checksum")
    collection = RecordingCollection(documents=[first, second])

    logs = await MongoAuditLogRepository(collection).list(skip=0, limit=100)

    assert [log.id for log in logs] == [str(first["_id"]), str(second["_id"])]
    assert logs[0].checksum == CHECKSUM
    assert logs[0].details == first["details"]


async def test_list_reports_a_storage_failure() -> None:
    """La lectura del listado falla como las demás: `503` reintentable."""
    collection = RecordingCollection(find_error=PyMongoError("localhost:27017 down"))

    with pytest.raises(AuditStorageError):
        await MongoAuditLogRepository(collection).list()


async def test_list_does_not_translate_a_programming_error() -> None:
    """Un fallo de mapeo (un documento sin los campos de §6.2) sube intacto:
    no es una indisponibilidad del almacenamiento."""
    collection = RecordingCollection(documents=[{"_id": ObjectId()}])

    with pytest.raises(KeyError):
        await MongoAuditLogRepository(collection).list()


async def test_find_by_checksum_filters_and_sorts_without_pagination() -> None:
    """SPEC §8.1 / D12: la consulta filtra sólo por `checksum` y ordena con la
    misma clave que el índice compuesto de §6.3, **sin** `.skip()` ni
    `.limit()` — el cliente Go no pagina el listado por checksum."""
    collection = RecordingCollection(documents=[make_document()])

    await MongoAuditLogRepository(collection).find_by_checksum(CHECKSUM)

    assert collection.queries == [{"checksum": CHECKSUM}]
    assert collection.sorts == [[("performed_at", -1), ("_id", -1)]]
    assert collection.skips == []
    assert collection.limits == []


async def test_find_by_checksum_returns_the_matches_as_domain_logs() -> None:
    """Las coincidencias llegan como registros de dominio: `_id` hex y fechas
    con zona, igual que en el listado global."""
    first = make_document()
    second = make_document(checksum="otro-checksum")
    collection = RecordingCollection(documents=[first, second])

    logs = await MongoAuditLogRepository(collection).find_by_checksum(CHECKSUM)

    assert [log.id for log in logs] == [str(first["_id"]), str(second["_id"])]
    assert logs[0].checksum == CHECKSUM


async def test_find_by_checksum_reports_a_storage_failure() -> None:
    """La lectura por checksum falla como las demás: `503` reintentable."""
    collection = RecordingCollection(find_error=PyMongoError("localhost:27017 down"))

    with pytest.raises(AuditStorageError):
        await MongoAuditLogRepository(collection).find_by_checksum(CHECKSUM)


async def test_find_by_checksum_does_not_translate_a_programming_error() -> None:
    """Un fallo de mapeo sube intacto: no es una indisponibilidad del storage."""
    collection = RecordingCollection(documents=[{"_id": ObjectId()}])

    with pytest.raises(KeyError):
        await MongoAuditLogRepository(collection).find_by_checksum(CHECKSUM)
