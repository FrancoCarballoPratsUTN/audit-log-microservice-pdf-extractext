"""Pruebas de las rutas de salud con MongoDB real."""

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import InvalidOperation

from app.main import create_app, lifespan
from app.repositories.mongodb import (
    CHECKSUM_LOOKUP_INDEX,
    GLOBAL_LOOKUP_INDEX,
    UNIQUE_IDEMPOTENCY_INDEX,
    audit_logs_collection,
)
from tests.integration.conftest import COLLECTION_NAME, TEST_TOKEN

TTL_INDEX_NAME = "ttl_performed_at"


def test_the_app_is_ready_against_a_real_mongo(deployed: None) -> None:
    """Con Mongo respondiendo, los cuatro pasos del arranque terminan y `/readyz` lo
    confirma.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.

    Returns:
        No retorna valor.
    """
    with TestClient(create_app()) as client:
        assert client.get("/readyz").status_code == 200
        assert client.get("/health").status_code == 200


def test_the_probes_do_not_need_credentials(deployed: None) -> None:
    """Un sondeo de plataforma no lleva token, y con credenciales válidas tampoco debe
    romperse: `PUBLIC_PATHS` las deja pasar, no las rechaza.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.

    Returns:
        No retorna valor.
    """
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert (
            client.get(
                "/readyz", headers={"Authorization": f"Bearer {TEST_TOKEN}"}
            ).status_code
            == 200
        )


async def test_the_lifespan_really_created_the_indexes(
    deployed: None, clean_collection: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El `lifespan` llama a `ensure_indexes` sin que nadie mire el resultado.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.
        monkeypatch: Utilidad de pytest para sustituir valores.

    Returns:
        No retorna valor.
    """
    monkeypatch.setenv("RETENTION_DAYS", "30")
    app = create_app()

    async with lifespan(app):
        collection = audit_logs_collection(app.state.mongo_client, app.state.settings)
        indexes = await collection.index_information()

    assert {
        UNIQUE_IDEMPOTENCY_INDEX.name,
        CHECKSUM_LOOKUP_INDEX.name,
        GLOBAL_LOOKUP_INDEX.name,
        TTL_INDEX_NAME,
    } <= set(indexes)


async def test_no_ttl_index_is_created_when_retention_is_zero(
    deployed: None, clean_collection: object
) -> None:
    """Con `RETENTION_DAYS=0` no hay TTL.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.

    Returns:
        No retorna valor.
    """
    app = create_app()

    async with lifespan(app):
        collection = audit_logs_collection(app.state.mongo_client, app.state.settings)
        indexes = await collection.index_information()

    assert TTL_INDEX_NAME not in indexes
    assert all("expireAfterSeconds" not in spec for spec in indexes.values())


async def test_the_indexes_land_in_the_configured_database(
    deployed: None, clean_collection: object, test_database: str
) -> None:
    """Un índice creado en otra base no protege de nada, y no se nota hasta que hay dos
    documentos con la misma identidad.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.
        test_database: Nombre de la base de datos de prueba.

    Returns:
        No retorna valor.
    """
    app = create_app()

    async with lifespan(app):
        client = app.state.mongo_client
        found = await client.get_database(test_database).list_collection_names()
        assert COLLECTION_NAME in found

        indexes = await audit_logs_collection(
            client, app.state.settings
        ).index_information()

    assert UNIQUE_IDEMPOTENCY_INDEX.name in indexes


async def test_stopping_the_app_closes_the_client(deployed: None) -> None:
    """Sin cierre, cada reinicio del despliegue deja un pool de conexiones colgando
    hasta que el sistema se queja.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.

    Returns:
        No retorna valor.
    """
    app = create_app()

    async with lifespan(app):
        await app.state.mongo_client.admin.command("ping")

    with pytest.raises(InvalidOperation):
        await app.state.mongo_client.admin.command("ping")


def test_the_service_reads_the_uri_from_the_environment(deployed: None) -> None:
    """Fija que `MONGO_URI` y `MONGO_DATABASE` del entorno son los que mandan, y no un
    default: valores por defecto equivocados crean índices donde nadie...

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.

    Returns:
        No retorna valor.
    """
    settings = create_app().state.settings

    assert settings.mongo_database == "pdf_extractext_audit_test"
    assert settings.mongo_audit_logs_collection == COLLECTION_NAME
