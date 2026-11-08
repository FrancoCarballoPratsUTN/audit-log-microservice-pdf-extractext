"""CORS: preflight válido 200, no abre rutas protegidas sin token."""

from fastapi.testclient import TestClient

from tests.unit.api._middleware_common import build_app


def build_client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


def test_cors_answers_a_preflight() -> None:
    """Starlette responde `200` a un preflight válido; se anota en el test en vez
    de envolver la librería."""
    client = build_client()
    response = client.options(
        "/health",
        headers={
            "Origin": "https://example.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_a_cross_origin_response_advertises_the_allowed_origin() -> None:
    client = build_client()
    response = client.get("/health", headers={"Origin": "https://example.test"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_cors_cannot_open_a_protected_route_without_a_token() -> None:
    """CORS vive por dentro de auth: el preflight de una ruta protegida sigue
    siendo `401`."""
    client = build_client()
    response = client.options(
        "/audit/logs",
        headers={
            "Origin": "https://example.test",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 401
