"""Rechazar con `413` un cuerpo sin tamaño declarado o por encima del límite.

El microservicio tiene un límite de tamaño para las solicitudes. 
Antes de procesar los datos, revisa la cabecera Content-Length para saber cuánto 
ocupa el contenido. Si supera el límite permitido, rechaza la solicitud sin necesidad 
de cargar todo el contenido en memoria. Esto ayuda a proteger los recursos del sistema"
"""

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from app.api.middleware.body_size import parse_content_length

from tests.unit.api._middleware_common import AUTH, JSON, LIMIT, build_app

MIDDLEWARE_SOURCE = (
    Path(__file__).resolve().parents[3] / "app" / "api" / "middleware" / "body_size.py"
)


def build_client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


def test_body_size_is_checked_before_validation() -> None:
    client = build_client()
    response = client.post(
        "/audit/logs", headers={**AUTH, **JSON}, content=b"x" * (LIMIT + 1)
    )

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_a_post_without_content_length_is_a_413() -> None:
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
    """`Content-Length` ausente o ilegible cuenta como 0, no revienta."""
    assert parse_content_length(value) == expected


def test_the_body_limit_never_reads_the_body() -> None:
    """Esta prueba revisa directamente el código fuente del middleware. 
    Busca que no se utilicen métodos para leer el body, como .body()
    Esto permite comprobar que el límite de tamaño se controle sin cargar
     el contenido de la solicitud en memoria."""
    source = MIDDLEWARE_SOURCE.read_text(encoding="utf-8")

    for reader in (".body(", ".stream(", "request.json", "request.data", ".form("):
        assert reader not in source, f"el límite de body no debe usar {reader}"
