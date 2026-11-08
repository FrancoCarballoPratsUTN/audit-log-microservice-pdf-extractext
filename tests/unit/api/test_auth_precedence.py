"""La autenticación (401) gana a cualquier otro chequeo"""

from tests.unit.api._middleware_common import AUTH, LIMIT, build_app

from fastapi.testclient import TestClient


def build_client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


def test_authentication_beats_every_other_check() -> None:
    """Esta prueba verifica que la autenticación se realice antes que
    las demás validaciones. Para eso enviamos una solicitud sin token, 
    con un body que supera el límite permitido y con un tipo de contenido
    incorrecto. Aunque tiene varios errores, esperamos que el servidor 
    responda 401, porque primero debe verificar que el cliente esté autenticado"""
    client = build_client()
    response = client.post(
        "/audit/logs",
        headers={"Content-Type": "text/plain"},
        content=b"x" * (LIMIT + 1),
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
