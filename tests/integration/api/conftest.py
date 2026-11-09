"""Prepara la aplicación y la base de datos de prueba."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app_client(deployed: None) -> Iterator[TestClient]:
    """Cliente de la app real contra el Mongo de pruebas.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.

    Returns:
        No retorna valor.
    """
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client
