"""Log de acceso: método, ruta, estado, duración y `request_id`."""

import logging

from fastapi.testclient import TestClient
import pytest

from tests.unit.api._middleware_common import AUTH, build_app


def build_client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


def test_the_access_log_records_method_path_status_and_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
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
    client = build_client()
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        client.get("/health", headers={"X-Request-ID": "trace-me"})

    assert any("trace-me" in record.getMessage() for record in caplog.records)


def test_an_unhandled_error_is_logged_and_becomes_a_500(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = build_client()
    with caplog.at_level(logging.ERROR, logger="app.api.middleware"):
        response = client.get("/boom", headers=AUTH)

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert any("boom" in record.getMessage() for record in caplog.records)
