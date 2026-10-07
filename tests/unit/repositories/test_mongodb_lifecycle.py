"""Lifecycle de Mongo: los índices de SPEC §6.3 como datos, no como efectos.

Un índice es configuración que no se ve hasta que se rompe. Si
`(checksum, performed_at desc, _id desc)` se crea sin el `_id desc`, todo sigue
funcionando: las consultas devuelven lo correcto, los tests de contenido pasan, y
sólo dos semanas después una página de `skip/limit` devuelve filas distintas entre
llamadas. Por eso los índices se declaran **como datos** en este módulo y se
traducen a `IndexModel` en el último momento: así se pueden afirmar sin abrir una
conexión.

`ping` sí necesita el driver, porque su trabajo es exactamente recibir la
excepción de él. Se prueba con el doble de `tests/fakes/fake_mongo.py`, que lanza
la excepción real de PyMongo: la traducción se define sobre las clases que el
driver levanta de verdad.

La verificación contra un MongoDB real vive en
`tests/integration/repositories/test_mongo_indexes.py`.
"""

import pytest
from pymongo.errors import (
    ConnectionFailure,
    ExecutionTimeout,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

from app.config import Settings, get_settings
from app.errors import AuditStorageError
from app.repositories.mongodb import (
    UNIQUE_IDEMPOTENCY_INDEX,
    audit_logs_collection,
    ensure_indexes,
    index_specs,
    open_client,
    ping,
    ttl_index,
)
from tests.fakes.fake_mongo import FailingClient, WorkingClient

SECRET_URI = "mongodb://auditor:contrasena-secreta@localhost:27017"


def build_settings(**overrides: object) -> Settings:
    """Ajustes sobre el mínimo válido."""
    return get_settings(environ={"SERVICE_API_TOKEN": "t", **overrides})


class RecordingCollection:
    """Colección que guarda los `IndexModel` que recibió, sin tocar Mongo."""

    def __init__(self) -> None:
        self.models: list[object] = []

    async def create_indexes(self, models: list[object]) -> list[str]:
        self.models = list(models)
        return [model.document["name"] for model in self.models]


def test_the_unique_index_covers_exactly_the_identity_tuple() -> None:
    """SPEC §6.3 fila 2: la idempotencia se decide sobre
    `(action, entity_type, checksum, performed_at)`, ni un campo más ni uno menos.
    Un checksum genera varios eventos, así que el checksum solo no basta."""
    assert UNIQUE_IDEMPOTENCY_INDEX.fields == (
        "action",
        "entity_type",
        "checksum",
        "performed_at",
    )


def test_the_unique_index_is_unique() -> None:
    """Sin `unique`, la Barrera 2 de §5.3 no existe y la carrera de T11 inserta
    duplicados."""
    assert UNIQUE_IDEMPOTENCY_INDEX.unique is True


def test_the_identity_index_does_not_sort_descending() -> None:
    """El índice único va en ascendente: MongoDB recorre un índice único al revés
    tan bien como al derecho, y aquí el desempate de §12 no aplica."""
    assert UNIQUE_IDEMPOTENCY_INDEX.descending == frozenset()


def test_the_checksum_lookup_ends_with_id_descending() -> None:
    """SPEC §6.3 fila 3 y §12: sin `_id desc` como desempate, dos eventos con el
    mismo `performed_at` se ordenarían de forma no determinista."""
    spec = next(
        spec
        for spec in index_specs(0)
        if spec.fields[0] == "checksum" and not spec.unique
    )

    assert spec.fields == ("checksum", "performed_at", "_id")
    assert spec.descending == frozenset({"performed_at", "_id"})


def test_the_global_lookup_ends_with_id_descending() -> None:
    """SPEC §6.3 fila 4 y §12: mismo motivo que el anterior, para
    `GET /audit/logs`."""
    spec = next(spec for spec in index_specs(0) if spec.fields[0] == "performed_at")

    assert spec.fields == ("performed_at", "_id")
    assert spec.descending == frozenset({"performed_at", "_id"})


def test_every_lookup_index_ends_with_id_descending() -> None:
    """Guard de §12 sobre la propiedad y no sobre un índice concreto: cualquier
    índice de lectura con más de un campo necesita el `_id` descendente al final
    como desempate.

    El índice único se excluye a propósito: su primera tupla ya es única, así que
    no hay dos filas que empatar y no necesita desempate.
    """
    lookups = [spec for spec in index_specs(0) if not spec.unique]

    assert len(lookups) == 2, "los dos índices de lectura de §6.3"
    for spec in lookups:
        assert len(spec.fields) > 1
        assert spec.fields[-1] == "_id"
        assert "_id" in spec.descending


def test_only_the_identity_index_is_unique() -> None:
    """Los otros dos son de lectura; hacerlos únicos convertiría un `GET` en un
    `409` inexplicable."""
    unique = [spec.name for spec in index_specs(0) if spec.unique]

    assert unique == [UNIQUE_IDEMPOTENCY_INDEX.name]


def test_no_ttl_index_when_retention_is_disabled() -> None:
    """`RETENTION_DAYS = 0` significa "retención desactivada", no "borrar ya": un
    TTL de 0 segundos vaciaría la auditoría entera."""
    assert ttl_index(0) is None
    assert all(spec.expire_after_seconds is None for spec in index_specs(0))


def test_the_ttl_index_is_built_when_retention_is_positive() -> None:
    spec = ttl_index(30)

    assert spec is not None
    assert spec.fields == ("performed_at",)
    assert spec.expire_after_seconds == 30 * 24 * 60 * 60


def test_the_ttl_index_is_the_only_fourth_one() -> None:
    """SPEC §6.3 tiene cuatro filas y sólo una es condicional."""
    assert len(index_specs(0)) == 3
    assert len(index_specs(30)) == 4
    assert index_specs(30)[-1].expire_after_seconds == 30 * 86400


def test_fields_render_as_ones_and_minus_ones_in_order() -> None:
    """El contrato de `IndexModel`: nombre del campo con `1`/`-1`, y el orden de
    la tupla es el orden del índice."""
    spec = next(spec for spec in index_specs(0) if spec.fields[0] == "checksum")

    assert spec.keys == [("checksum", 1), ("performed_at", -1), ("_id", -1)]


def test_the_index_model_carries_its_name_and_its_flags() -> None:
    """`getIndexes()` en `mongosh` tiene que mostrar lo que SPEC §6.3 promete, con
    nombre estable para poder citarlo en el handoff."""
    model = UNIQUE_IDEMPOTENCY_INDEX.to_index_model()

    assert model.document["name"] == UNIQUE_IDEMPOTENCY_INDEX.name
    assert model.document["unique"] is True

    spec = ttl_index(7)
    assert spec is not None
    assert spec.to_index_model().document["expireAfterSeconds"] == 7 * 86400


async def test_ensure_indexes_hands_the_collection_every_spec() -> None:
    """Un bucle que se comiera un índice por el camino no se vería en ningún test
    de contenido: sólo se ve contando lo que llega a la colección."""
    collection = RecordingCollection()

    await ensure_indexes(collection, retention_days=30)

    assert len(collection.models) == 4


def test_the_client_is_built_with_the_configured_timeout() -> None:
    """Sin `serverSelectionTimeoutMS`, un Mongo caído bloquea el arranque el
    tiempo por defecto del driver (30 s) en vez del `MONGO_TIMEOUT_MS` del
    despliegue."""
    client = open_client(build_settings(mongo_timeout_ms="2500"))

    assert client.options.server_selection_timeout == 2.5


def test_the_collection_lands_in_the_configured_database() -> None:
    """Escribir en la base equivocada no falla: deja los datos en otro sitio donde
    nadie los busca, que es peor que un error."""
    settings = build_settings(
        mongo_database="otro_db", mongo_audit_logs_collection="otra_coleccion"
    )

    collection = audit_logs_collection(open_client(settings), settings)

    assert collection.database.name == "otro_db"
    assert collection.name == "otra_coleccion"


@pytest.mark.parametrize(
    "error",
    [
        ServerSelectionTimeoutError("localhost:27017: timed out"),
        ConnectionFailure("connection refused"),
        ExecutionTimeout("operation exceeded time limit"),
        PyMongoError("algo que el driver no tenía previsto"),
    ],
    ids=["sin-servidor", "red-caida", "operacion-lenta", "driver-inesperado"],
)
async def test_ping_reports_an_unavailable_storage(error: Exception) -> None:
    """SPEC §6.4: Mongo inalcanzable es `503` y no `500`, porque quien llama puede
    reintentar. Y sale como `AuditStorageError`, que es lo que traduce la Capa 1."""
    with pytest.raises(AuditStorageError):
        await ping(FailingClient(error))


async def test_ping_never_leaks_the_credentials_of_the_uri() -> None:
    """El detalle de un fallo de conexión suele traer `host:port`, y con él parte
    de la URI. Esa variable acaba en logs ajenos al servicio y en capturas de
    pantalla."""
    with pytest.raises(AuditStorageError) as failure:
        await ping(FailingClient(ServerSelectionTimeoutError(SECRET_URI)))

    assert "contrasena-secreta" not in failure.value.detail
    assert SECRET_URI not in failure.value.detail


async def test_ping_does_not_swallow_a_programming_error() -> None:
    """Una `TypeError` o un `AttributeError` en nuestro código no es un problema de
    infraestructura: traducirla a `503` haría que un bug pareciera una caída de
    Mongo y escondería el defecto detrás de un reintento del Orquestador."""

    class ExplodingAdmin:
        async def command(self, name: str) -> dict[str, float]:
            raise TypeError("se esperaba un dict, llegó otra cosa")

    class ExplodingClient:
        admin = ExplodingAdmin()

    with pytest.raises(TypeError):
        await ping(ExplodingClient())


async def test_ping_says_nothing_when_mongo_answers() -> None:
    """El camino feliz no debe fabricar un error ni devolver nada que el lifespan
    tenga que interpretar."""
    assert await ping(WorkingClient()) is None


@pytest.mark.parametrize(
    "error",
    [
        ServerSelectionTimeoutError("localhost:27017: timed out"),
        ConnectionFailure("connection refused"),
        OperationFailure("an existing index has different options"),
    ],
    ids=["sin-servidor", "red-caida", "indice-en-conflicto"],
)
async def test_ensure_indexes_reports_an_unavailable_storage(
    error: Exception,
) -> None:
    """SPEC §6.4 aplicado a la creación de índices.

    El caso real no es inventado: `create_indexes` falla con `OperationFailure` si
    un índice del mismo nombre ya existe con otras opciones, que es justo lo que
    pasa al desplegar sobre una base creada por una versión anterior. Si eso saliera
    como `500`, el Orquestador no lo reintentaría y el servicio no volvería a
    levantar sus índices ni al reiniciar."""

    class RejectingCollection:
        async def create_indexes(self, models: list[object]) -> list[str]:
            raise error

    with pytest.raises(AuditStorageError):
        await ensure_indexes(RejectingCollection(), retention_days=30)


@pytest.mark.parametrize(
    "driver_message",
    [
        "localhost:27017: timed out",
        f"an existing index has different options at {SECRET_URI}",
        f"connection refused while authenticating {SECRET_URI}",
        "escritura en auditoria.reconocimiento: contrasena-secreta",
    ],
    ids=["host-y-puerto", "indice-con-uri", "autenticacion-con-uri", "passphrase"],
)
async def test_ensure_indexes_never_leaks_what_the_driver_said(
    driver_message: str,
) -> None:
    """El detalle del error es lo que sale hacia el cliente y lo que acaba en los
    logs de quien recibe el `503`. El driver mete `host:port`, y a veces la URI
    entera o el motivo de autenticación, en sus mensajes. Este servicio responde
    siempre con su propio texto y descarta el del driver: el diagnóstico va al log
    del servidor, que controlamos, y no a una respuesta que puede acabar en una
    captura de pantalla."""

    class LeakyCollection:
        async def create_indexes(self, models: list[object]) -> list[str]:
            raise OperationFailure(driver_message)

    with pytest.raises(AuditStorageError) as failure:
        await ensure_indexes(LeakyCollection(), retention_days=30)

    assert failure.value.detail == "MongoDB indexes could not be created."


async def test_ensure_indexes_does_not_swallow_a_programming_error() -> None:
    """Si pasáramos una lista de `IndexModel` mal construida, un `TypeError` es un
    bug nuestro y no una caída de Mongo: traducirlo a `503` lo escondería detrás de
    un reintento que no puede arreglarlo."""

    class ExplodingCollection:
        async def create_indexes(self, models: list[object]) -> list[str]:
            raise TypeError("models no es una lista de IndexModel")

    with pytest.raises(TypeError):
        await ensure_indexes(ExplodingCollection(), retention_days=30)
