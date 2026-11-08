"""Replay idempotente y validaciones de entrada (400 / 413)."""

import pytest

from tests.integration.api.helpers import VALID_EVENT, AUTH, app_client


async def test_an_identical_event_is_a_replay_and_leaves_one_document(
    deployed: None, clean_collection: object
) -> None:
    """El reintento del orquestador (SPEC §5.3) responde `200` con el log
    original, nunca inserta un segundo documento."""
    with app_client() as client:
        first = client.post("/audit/logs", json=VALID_EVENT, headers=AUTH)
        second = client.post("/audit/logs", json=VALID_EVENT, headers=AUTH)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["X-Idempotent-Replay"] == "true"
    assert second.headers["Location"] == first.headers["Location"]
    body = second.json()
    assert body["idempotent_replay"] is True
    assert body["_id"] == first.json()["_id"]

    documents = await clean_collection.find({}).to_list(None)
    assert len(documents) == 1


def test_missing_required_field_is_400_validation_error(deployed: None) -> None:
    payload = {k: v for k, v in VALID_EVENT.items() if k != "action"}

    with app_client() as client:
        response = client.post("/audit/logs", json=payload, headers=AUTH)

    assert response.status_code == 400
    body = response.json()
    assert body["type"] == "/problems/validation_error"
    assert body["status"] == 400
    assert body["code"] == "VALIDATION_ERROR"
    assert body["instance"] == "/audit/logs"


def test_unknown_top_level_key_is_400(deployed: None) -> None:
    """`extra="forbid"` (SPEC §3.4): un 201 que descarta `user_id` en silencio es
    el peor fallo posible en una auditoría."""
    with app_client() as client:
        response = client.post(
            "/audit/logs", json={**VALID_EVENT, "user_id": "u-1"}, headers=AUTH
        )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_performed_at_without_offset_is_400(deployed: None) -> None:
    """`AwareDatetime`: una fecha naive no localiza el evento, se rechaza."""
    with app_client() as client:
        response = client.post(
            "/audit/logs",
            json={**VALID_EVENT, "performed_at": "2026-10-05T12:34:56"},
            headers=AUTH,
        )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_details_over_the_limit_is_413_and_nothing_is_written(
    deployed: None, clean_collection: object
) -> None:
    """SPEC §4.4 paso 6: el límite de `details` se comprueba antes de la Capa 2."""
    event = {**VALID_EVENT, "details": {"blob": "x" * 70000}}

    with app_client() as client:
        response = client.post("/audit/logs", json=event, headers=AUTH)

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert await clean_collection.count_documents({}) == 0


@pytest.mark.parametrize(
    "details_json",
    [
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":-Infinity}',
        '{"value":18446744073709551616}',
        r'{"bad\u0000key":1}',
        "[" * 5000 + "0" + "]" * 5000,
    ],
    ids=[
        "nan",
        "infinity",
        "negative-infinity",
        "integer-overflow",
        "nul-key",
        "too-deep",
    ],
)
async def test_invalid_details_are_400_and_do_not_poison_the_listing(
    deployed: None, clean_collection: object, details_json: str
) -> None:
    """T19: ningún detalle que BSON no puede guardar deja un documento a medias
    que haga fallar el `GET` siguiente."""
    body = RAW_EVENT_PREFIX + details_json + "}"
    headers = {**AUTH, "Content-Type": "application/json"}

    with app_client() as client:
        response = client.post("/audit/logs", content=body, headers=headers)
        listing = client.get("/audit/logs", headers=AUTH)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert await clean_collection.count_documents({}) == 0
    assert listing.status_code == 200
    assert listing.json() == []
