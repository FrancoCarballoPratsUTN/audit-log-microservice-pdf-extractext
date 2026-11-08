"""Ninguna ruta responde 422: todo JSON inválido es 400 (SPEC §3.3 D1, §2.6)."""

from fastapi.testclient import TestClient

from tests.integration.api.helpers import AUTH, VALID_EVENT


def test_no_route_ever_answers_422(deployed: None, app_client: TestClient) -> None:
    """La garantía negativa que sostiene todo lo demás: el `422` de FastAPI
    no sale nunca, ni siquiera ante JSON malformado."""
    malformed = [
        app_client.post(
            "/audit/logs", json={**VALID_EVENT, "user_id": "u-1"}, headers=AUTH
        ),
        app_client.post("/audit/logs", json={"action": "x"}, headers=AUTH),
        app_client.post(
            "/audit/logs",
            json={**VALID_EVENT, "performed_at": "2026-10-05T12:34:56"},
            headers=AUTH,
        ),
        app_client.post(
            "/audit/logs",
            content=b"not json",
            headers={**AUTH, "Content-Type": "application/json"},
        ),
        app_client.post(
            "/audit/logs",
            content=b"[]",
            headers={**AUTH, "Content-Type": "application/json"},
        ),
        app_client.get("/audit/logs", params={"skip": -1}, headers=AUTH),
        app_client.get("/audit/logs", params={"limit": 0}, headers=AUTH),
    ]

    assert [response.status_code for response in malformed] == [400] * len(malformed)
