"""Pruebas del orden de las validaciones."""

from fastapi.testclient import TestClient

from tests.unit.api._middleware_common import AUTH, JSON, build_app


def build_client() -> TestClient:
    """Crea un cliente para la aplicación de prueba."""
    return TestClient(build_app(), raise_server_exceptions=False)


def test_validation_is_the_last_gate() -> None:
    """Con token, `application/json` y body pequeño, el fallo que queda es el de
    estructura: `400`, nunca el `422` de FastAPI
    """
    client = build_client()
    accepted = client.post(
        "/audit/logs", headers={**AUTH, **JSON}, content=b'{"action":"pdf.extract"}'
    )
    rejected = client.post("/audit/logs", headers={**AUTH, **JSON}, content=b"{nope")

    assert accepted.status_code == 201
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "VALIDATION_ERROR"
