"""Fixtures compartidas de los tests de integración de la capa HTTP.

Los tests de este directorio ejercitan la app real (con su lifespan, su
middleware y su Mongo) en vez de montarla a mano: lo que se afirma es el
comportamiento del cable, no el de una copia que puede divergir del despliegue.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app_client(deployed: None) -> Iterator[TestClient]:
    """Cliente de la app real contra el Mongo de pruebas."""
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client
