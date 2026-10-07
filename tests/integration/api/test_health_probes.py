"""El arranque contra un MongoDB de verdad.

Los tests unitarios de `tests/unit/api/routers/test_health.py` cubren el camino
malo: Mongo inalcanzable, la app arranca igualmente y `/readyz` dice `503`. Este
módulo cubre el camino bueno, que es el único que crea índices de verdad.

La prueba que importa es `test_the_lifespan_really_created_the_indexes`: el
lifespan llama a `ensure_indexes` en silencio, y una llamada que nadie verifica
puede no estar ocurrir, apuntar a la colección equivocada o tragarse el error.
Aquí se lee el resultado desde el otro lado, con `index_information()`.

Los tests que necesitan `await` invocan el `lifespan` directamente en vez de usar
`TestClient`: el cliente de Mongo queda atado al event loop que lo creó, y
`TestClient` corre en el suyo.
"""

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
    """SPEC §6.5: con Mongo respondiendo, los cuatro pasos del arranque terminan y
    `/readyz` lo confirma."""
    with TestClient(create_app()) as client:
        assert client.get("/readyz").status_code == 200
        assert client.get("/health").status_code == 200


def test_the_probes_do_not_need_credentials(deployed: None) -> None:
    """Un sondeo de plataforma no lleva token, y con credenciales válidas tampoco
    debe romperse: `PUBLIC_PATHS` las deja pasar, no las rechaza."""
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

    Pide `clean_collection` sólo por su efecto: sin ella, los índices que quedan
    aquí podrían ser los de otro test, y la comprobación no probaría nada."""
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
    """§6.3 lo dice en condicional: con `RETENTION_DAYS=0` no hay TTL. Un índice con
    `expireAfterSeconds: 0` vaciaría la auditoría segundos después de arrancar.

    Esta prueba es la razón de que `clean_collection` exista: MongoDB nunca borra
    un índice, así que un `ttl_performed_at` del test anterior haría pasar esta
    comprobación sin que el lifespan hubiera hecho nada."""
    app = create_app()

    async with lifespan(app):
        collection = audit_logs_collection(app.state.mongo_client, app.state.settings)
        indexes = await collection.index_information()

    assert TTL_INDEX_NAME not in indexes
    assert all("expireAfterSeconds" not in spec for spec in indexes.values())


async def test_the_indexes_land_in_the_configured_database(
    deployed: None, clean_collection: object, test_database: str
) -> None:
    """Un índice creado en otra base no protege de nada, y no se nota hasta que hay
    dos documentos con la misma identidad."""
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
    """Sin cierre, cada reinicio del despliegue deja un pool de conexiones
    colgando hasta que el sistema se queja."""
    app = create_app()

    async with lifespan(app):
        await app.state.mongo_client.admin.command("ping")

    with pytest.raises(InvalidOperation):
        await app.state.mongo_client.admin.command("ping")


def test_the_service_reads_the_uri_from_the_environment(deployed: None) -> None:
    """Fija que `MONGO_URI` y `MONGO_DATABASE` del entorno son los que mandan, y no
    un default: valores por defecto equivocados crean índices donde nadie los
    mira."""
    settings = create_app().state.settings

    assert settings.mongo_database == "pdf_extractext_audit_test"
    assert settings.mongo_audit_logs_collection == COLLECTION_NAME
