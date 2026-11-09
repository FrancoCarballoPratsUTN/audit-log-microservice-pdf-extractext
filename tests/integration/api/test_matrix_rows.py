"""Pruebas de todas las filas de la matriz de errores."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.api._matrix_common import (
    PROBLEM_MEDIA_TYPE,
    REQUIRED_PROBLEM_MEMBERS,
    ROWS,
)


@pytest.mark.parametrize("row", ROWS, ids=[row.code for row in ROWS])
async def test_every_row_of_the_matrix(
    row, deployed: None, clean_collection: object, app_client: TestClient
) -> None:
    """Las ocho filas de SPEC §7.2, con su status y su `code` exactos, y la regla de
    httpclient/client.go:39: todo `>= 300` trae un problem details con `t...

    Args:
        row: Fila de la matriz de errores.
        deployed: Aplicación preparada contra MongoDB de prueba.
        clean_collection: Colección de prueba vacía.
        app_client: Cliente de la aplicación.

    Returns:
        No retorna valor.
    """
    if row.arrange is not None:
        await row.arrange(clean_collection)

    response = row.send(app_client)

    assert response.status_code == row.status
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)

    body = response.json()
    assert body["code"] == row.code
    assert body["status"] == row.status
    assert body["instance"] == row.instance
    assert set(body) >= REQUIRED_PROBLEM_MEMBERS
