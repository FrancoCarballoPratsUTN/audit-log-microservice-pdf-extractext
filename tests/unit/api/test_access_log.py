"""Pruebas del registro de acceso."""

import logging

import pytest
from fastapi.testclient import TestClient

from tests.unit.api._middleware_common import AUTH, build_app


def build_client() -> TestClient:
    """Crea un cliente para la aplicación de prueba."""
    return TestClient(build_app(), raise_server_exceptions=False)


def test_the_access_log_records_method_path_status_and_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Comprueba que el registro guarda método, ruta, estado y duración.

    Args:
        caplog: Capturador de registros de pytest.

    Returns:
        No retorna valor.
    """
    client = build_client()
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        client.get("/health")

    messages = [
        record.getMessage()
        for record in caplog.records
        if "GET /health" in record.getMessage()
    ]
    assert len(messages) == 1
    assert "200" in messages[0]
    assert "ms" in messages[0]


def test_the_access_log_carries_the_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Comprueba que el registro incluye el identificador de la petición.

    Args:
        caplog: Capturador de registros de pytest.

    Returns:
        No retorna valor.
    """
    client = build_client()
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        client.get("/health", headers={"X-Request-ID": "trace-me"})

    assert any("trace-me" in record.getMessage() for record in caplog.records)


def test_an_unhandled_error_is_logged_and_becomes_a_500(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Comprueba que un error no controlado se registra y devuelve 500.

    Args:
        caplog: Capturador de registros de pytest.

    Returns:
        No retorna valor.
    """
    client = build_client()
    with caplog.at_level(logging.ERROR, logger="app.api.middleware"):
        response = client.get("/boom", headers=AUTH)

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert any("boom" in record.getMessage() for record in caplog.records)
