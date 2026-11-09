"""Comprueba que ninguna ruta responde 422."""

from fastapi.testclient import TestClient

from tests.integration.api.helpers import AUTH, VALID_EVENT


def test_no_route_ever_answers_422(deployed: None, app_client: TestClient) -> None:
    """La garantía negativa que sostiene todo lo demás: el `422` de FastAPI no sale
    nunca, ni siquiera ante JSON malformado.

    Args:
        deployed: Aplicación preparada contra MongoDB de prueba.
        app_client: Cliente de la aplicación.

    Returns:
        No retorna valor.
    """
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
