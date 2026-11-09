"""Pruebas de métodos no permitidos en auditorías."""
import pytest
from fastapi.testclient import TestClient

from tests.integration.api.helpers import AUTH, VALID_EVENT


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
async def test_put_and_delete_on_the_collection_are_405(
    method, deployed: None, app_client: TestClient
) -> None:
    """Un log de auditoría es append-only: los dos verbos de mutación sobre
    `/audit/logs` responden `405`.

    Args:
        method: Método HTTP.
        deployed: Aplicación preparada contra MongoDB de prueba.
        app_client: Cliente de la aplicación.

    Returns:
        No retorna valor.
    """
    response = app_client.request(method, "/audit/logs", json=VALID_EVENT, headers=AUTH)

    assert response.status_code == 405
    assert response.json()["code"] == "METHOD_NOT_ALLOWED"
