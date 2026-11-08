"""Exigir `application/json` en el `POST` → `415`."""

import pytest

from fastapi.testclient import TestClient

from tests.unit.api._middleware_common import AUTH, JSON, LIMIT, build_app


def build_client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/xml", "application/json-patch+json", ""],
    ids=["text/plain", "xml", "json-patch", "ausente"],
)
def test_post_without_json_content_type_is_415(content_type: str) -> None:
    client = build_client()
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": content_type},
        content=b"{}",
    )

    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_a_json_content_type_with_parameters_is_accepted() -> None:
    client = build_client()
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": "application/json; charset=utf-8"},
        content=b'{"action":"pdf.extract"}',
    )

    assert response.status_code == 201


def test_a_get_does_not_require_a_content_type() -> None:
    client = build_client()
    assert client.get("/health").status_code == 200


def test_content_type_is_checked_before_body_size() -> None:
    client = build_client()
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": "text/plain"},
        content=b"x" * (LIMIT + 1),
    )

    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"
