"""Prepara MongoDB y la configuración de las pruebas."""

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from pymongo import AsyncMongoClient, MongoClient
from pymongo.errors import OperationFailure, PyMongoError

from app.config import get_settings
from app.repositories.mongodb import audit_logs_collection

TEST_DATABASE_SUFFIX = "_test"
DEFAULT_URI = "mongodb://localhost:27017"
DEFAULT_DATABASE = "pdf_extractext_audit_test"
COLLECTION_NAME = "audit_logs_test"
PROBE_TIMEOUT_MS = 1500
TEST_TOKEN = "token-de-prueba"


def redact(uri: str) -> str:
    """La URI sin su contraseña, para poder imprimirla en un mensaje de error.

    Args:
        uri: URI de conexión.

    Returns:
        La URI sin contraseña.
    """
    if "@" not in uri:
        return uri
    scheme, _, rest = uri.partition("://")
    _, _, host = rest.partition("@")
    return f"{scheme}://***@{host}"


@pytest.fixture(scope="session")
def mongo_uri() -> str:
    """URI del MongoDB de pruebas, o `skip` si no hay nadie escuchando."""
    uri = os.environ.get("MONGO_URI", DEFAULT_URI)
    probe = MongoClient(uri, serverSelectionTimeoutMS=PROBE_TIMEOUT_MS)
    try:
        probe.admin.command("ping")
    except OperationFailure as exc:
        pytest.fail(
            f"MongoDB responde en {redact(uri)} pero rechaza las credenciales "
            f"(código {exc.code}). Define MONGO_URI con usuario, contraseña y "
            "authSource=admin, por ejemplo "
            "mongodb://usuario:clave@localhost:27017/?authSource=admin"
        )
    except PyMongoError:
        pytest.skip(
            f"no hay MongoDB en {redact(uri)}: define MONGO_URI para correr los "
            "tests de integración (SPEC §14)"
        )
    finally:
        probe.close()

    return uri


@pytest.fixture(scope="session")
def test_database() -> Iterator[str]:
    """Base de datos exclusiva de los tests, con el nombre guardado por seguridad."""
    name = os.environ.get("MONGO_TEST_DATABASE", DEFAULT_DATABASE)

    assert name.endswith(TEST_DATABASE_SUFFIX), (
        f"los tests de integración borran colecciones: '{name}' debe acabar en "
        f"'{TEST_DATABASE_SUFFIX}' para no tocar la base de despliegue"
    )

    yield name


@pytest.fixture
async def mongo_client(
    mongo_uri: str, test_database: str
) -> AsyncIterator[AsyncMongoClient[dict[str, object]]]:
    """Cliente contra la base de pruebas, cerrado al terminar.

    Args:
        mongo_uri: URI de conexión a MongoDB.
        test_database: Nombre de la base de datos de prueba.

    Returns:
        No retorna valor.
    """
    client = AsyncMongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
    try:
        yield client
    finally:
        await client.drop_database(test_database)
        await client.close()


@pytest.fixture
async def clean_collection(
    mongo_client: AsyncMongoClient[dict[str, object]], test_database: str
) -> AsyncIterator[object]:
    """Colección `audit_logs_test` recién creada, sin índices ni documentos.

    Args:
        mongo_client: Cliente de MongoDB.
        test_database: Nombre de la base de datos de prueba.

    Returns:
        No retorna valor.
    """
    settings = get_settings(
        environ={
            "SERVICE_API_TOKEN": TEST_TOKEN,
            "MONGO_DATABASE": test_database,
            "MONGO_AUDIT_LOGS_COLLECTION": COLLECTION_NAME,
        }
    )
    collection = audit_logs_collection(mongo_client, settings)
    await collection.drop()

    yield collection


@pytest.fixture
def deployed(
    monkeypatch: pytest.MonkeyPatch, mongo_uri: str, test_database: str
) -> None:
    """Apunta la configuración del despliegue a la base de pruebas.

    Args:
        monkeypatch: Utilidad de pytest para sustituir valores.
        mongo_uri: URI de conexión a MongoDB.
        test_database: Nombre de la base de datos de prueba.

    Returns:
        No retorna valor.
    """
    monkeypatch.setenv("SERVICE_API_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("MONGO_URI", mongo_uri)
    monkeypatch.setenv("MONGO_DATABASE", test_database)
    monkeypatch.setenv("MONGO_AUDIT_LOGS_COLLECTION", COLLECTION_NAME)
    monkeypatch.setenv("RETENTION_DAYS", "0")
