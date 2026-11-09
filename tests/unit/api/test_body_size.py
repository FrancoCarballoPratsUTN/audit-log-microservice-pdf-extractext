"""Pruebas del límite de tamaño del cuerpo."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.middleware.body_size import parse_content_length
from tests.unit.api._middleware_common import AUTH, JSON, LIMIT, build_app

MIDDLEWARE_SOURCE = (
    Path(__file__).resolve().parents[3] / "app" / "api" / "middleware" / "body_size.py"
)


def build_client() -> TestClient:
    """Crea un cliente para la aplicación de prueba."""
    return TestClient(build_app(), raise_server_exceptions=False)


def test_body_size_is_checked_before_validation() -> None:
    """Comprueba que el tamaño del cuerpo se revisa antes de validar."""
    client = build_client()
    response = client.post(
        "/audit/logs", headers={**AUTH, **JSON}, content=b"x" * (LIMIT + 1)
    )

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_a_post_without_content_length_is_a_413() -> None:
    """Comprueba que un POST sin tamaño de contenido devuelve 413."""
    client = build_client()
    request = client.build_request(
        "POST",
        "/audit/logs",
        headers={**AUTH, **JSON},
        content=b'{"action":"pdf.extract"}',
    )
    del request.headers["content-length"]

    response = client.send(request)

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_a_chunked_post_is_a_413() -> None:
    """Comprueba que un POST por partes devuelve 413."""
    client = build_client()
    response = client.post(
        "/audit/logs",
        headers={**AUTH, **JSON},
        content=iter([b'{"action":"pdf.extract"}']),
    )

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 0),
        ("", 0),
        ("abc", 0),
        ("-10", 0),
        ("0", 0),
        ("1024", 1024),
    ],
    ids=["ausente", "vacío", "no numérico", "negativo", "cero", "válido"],
)
def test_content_length_is_parsed_defensively(value: str | None, expected: int) -> None:
    """`Content-Length` ausente o ilegible cuenta como 0, no revienta.

    Args:
        value: Valor que se va a revisar.
        expected: Valor esperado.

    Returns:
        No retorna valor.
    """
    assert parse_content_length(value) == expected


def test_the_body_limit_never_reads_the_body() -> None:
    """Esta prueba revisa directamente el código fuente del middleware."""
    source = MIDDLEWARE_SOURCE.read_text(encoding="utf-8")

    for reader in (".body(", ".stream(", "request.json", "request.data", ".form("):
        assert reader not in source, f"el límite de body no debe usar {reader}"
