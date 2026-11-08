"""`X-Request-ID`: generado si falta o no es seguro."""

import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.unit.api._middleware_common import AUTH, build_app


def build_client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


def test_an_incoming_request_id_is_echoed() -> None:
    client = build_client()
    response = client.get("/health", headers={"X-Request-ID": "3f2a91c8e7b4d05a"})

    assert response.headers["x-request-id"] == "3f2a91c8e7b4d05a"


def test_a_missing_request_id_is_generated() -> None:
    client = build_client()
    response = client.get("/health")

    assert response.headers["x-request-id"]


@pytest.mark.parametrize(
    "value",
    ["   ", "x" * 65, "no valido"],
    ids=["vacío", "demasiado largo", "espacio"],
)
def test_an_invalid_request_id_is_regenerated(value: str) -> None:
    client = build_client()
    response = client.get("/health", headers={"X-Request-ID": value})

    assert uuid.UUID(response.headers["x-request-id"])


def test_newlines_in_a_request_id_do_not_reach_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = build_client()
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        response = client.get("/health", headers={"X-Request-ID": "trace\nINJECTED"})

    assert "INJECTED" not in caplog.text
    assert "\n" not in response.headers["x-request-id"]


def test_the_request_id_survives_a_rejected_request() -> None:
    """La razón de que `RequestId` corra por fuera del `415`: un rechazo también
    debe poder correlacionarse con su petición."""
    client = build_client()
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": "text/plain", "X-Request-ID": "trace-me"},
        content=b"{}",
    )

    assert response.status_code == 415
    assert response.headers["x-request-id"] == "trace-me"
