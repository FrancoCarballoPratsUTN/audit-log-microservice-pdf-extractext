"""Pruebas del orden entre autenticación y otras revisiones."""

from fastapi.testclient import TestClient

from tests.unit.api._middleware_common import LIMIT, build_app


def build_client() -> TestClient:
    """Crea un cliente para la aplicación de prueba."""
    return TestClient(build_app(), raise_server_exceptions=False)


def test_authentication_beats_every_other_check() -> None:
    """Esta prueba verifica que la autenticación se realice antes que las demás
    validaciones.
    """
    client = build_client()
    response = client.post(
        "/audit/logs",
        headers={"Content-Type": "text/plain"},
        content=b"x" * (LIMIT + 1),
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
