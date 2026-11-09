"""Pruebas del tipo de contenido JSON."""

import pytest
from fastapi.testclient import TestClient

from tests.unit.api._middleware_common import AUTH, LIMIT, build_app


def build_client() -> TestClient:
    """Crea un cliente para la aplicación de prueba."""
    return TestClient(build_app(), raise_server_exceptions=False)


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/xml", "application/json-patch+json", ""],
    ids=["text/plain", "xml", "json-patch", "ausente"],
)
def test_post_without_json_content_type_is_415(content_type: str) -> None:
    """Comprueba que un POST sin tipo JSON devuelve 415.

    Args:
        content_type: Tipo de contenido.

    Returns:
        No retorna valor.
    """
    client = build_client()
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": content_type},
        content=b"{}",
    )

    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_a_json_content_type_with_parameters_is_accepted() -> None:
    """Comprueba que un tipo JSON con parámetros se acepta."""
    client = build_client()
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": "application/json; charset=utf-8"},
        content=b'{"action":"pdf.extract"}',
    )

    assert response.status_code == 201


def test_a_get_does_not_require_a_content_type() -> None:
    """Comprueba que un GET no exige tipo de contenido."""
    client = build_client()
    assert client.get("/health").status_code == 200


def test_content_type_is_checked_before_body_size() -> None:
    """Comprueba que el tipo se revisa antes del tamaño."""
    client = build_client()
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": "text/plain"},
        content=b"x" * (LIMIT + 1),
    )

    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"
