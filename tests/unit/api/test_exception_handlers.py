"""Exception handlers: la traducción HTTP de la Capa 1.

Este módulo carga la garantía de mayor riesgo del servicio. El cliente de Go
parsea cualquier cuerpo con `status >= 300` como un problema, y la respuesta `422`
de FastAPI no satisface ese contrato: decodifica en un `Problem{}` con todos los
campos a cero, el orquestador luego llama a `WriteHeader(0)` y el servidor de Go
**hace panic** (SPEC §2.6). Así que `422` no debe poder salir de este servicio.

`app/main.py` existe ya, pero la app bajo test se construye aquí. Usa rutas
reales para que los fallos de validación y de enrutado sean los auténticos del
framework, no imitaciones levantadas a mano.
"""

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.exception_handlers import register_exception_handlers
from app.api.problem import PROBLEM_MEDIA_TYPE
from app.api.schemas import AuditEventRequest
from app.errors import AuditStorageError, NotFoundError, ValidationError

SENTINEL = "s3cr3t-token-value-that-must-never-be-echoed"


def build_app() -> FastAPI:
    """App mínima con las tres fuentes de fallo bajo test."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.post(
        "/audit/logs",
        responses={"4XX": {"description": "Client error"}},
    )
    async def create_audit_log(payload: AuditEventRequest) -> dict[str, Any]:
        return {"echo": payload.action}

    @app.get("/boom")
    async def raise_domain_error() -> None:
        raise AuditStorageError("the driver said something private")

    @app.get("/explode")
    async def raise_unexpected_error() -> None:
        raise RuntimeError("connection string with a password in it")

    @app.get("/teapot")
    async def raise_unmapped_http_error() -> None:
        raise StarletteHTTPException(status_code=418, detail="I am a teapot")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


def test_invalid_body_is_answered_with_400_not_422(client: TestClient) -> None:
    """La garantía que protege al orquestador de `WriteHeader(0)`."""
    response = client.post("/audit/logs", json={"action": "pdf.extract"})

    assert response.status_code == 400


def test_invalid_body_uses_the_validation_error_code(client: TestClient) -> None:
    response = client.post("/audit/logs", json={"action": "pdf.extract"})

    assert response.json()["code"] == "VALIDATION_ERROR"


def test_invalid_body_is_answered_with_the_problem_media_type(
    client: TestClient,
) -> None:
    response = client.post("/audit/logs", json={"action": "pdf.extract"})

    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)


def test_unknown_top_level_key_is_a_400(client: TestClient) -> None:
    response = client.post(
        "/audit/logs",
        json={
            "action": "pdf.extract",
            "entity_type": "document",
            "checksum": "abc",
            "performed_at": "2026-10-05T12:34:56Z",
            "user_id": "u-1",
        },
    )

    assert response.status_code == 400


def test_validation_detail_points_at_the_offending_field(client: TestClient) -> None:
    response = client.post(
        "/audit/logs",
        json={
            "action": "pdf.extract",
            "entity_type": "document",
            "checksum": "abc",
            "performed_at": "not-a-date",
        },
    )

    assert "performed_at" in response.json()["detail"]


def test_validation_detail_never_echoes_the_submitted_value(client: TestClient) -> None:
    """Un valor rechazado puede ser un token o un checksum. Reenviarlo convertiría
    el cuerpo del error en una segunda copia del secreto (SPEC §7.1)."""
    response = client.post(
        "/audit/logs",
        json={
            "action": "pdf.extract",
            "entity_type": "document",
            "checksum": {"nested": SENTINEL},
            "performed_at": "2026-10-05T12:34:56Z",
        },
    )

    assert SENTINEL not in response.text


def test_validation_detail_never_exposes_the_internal_context(
    client: TestClient,
) -> None:
    """El `ctx` y el `url` de Pydantic apuntan a internos de la pila de
    validación."""
    response = client.post("/audit/logs", json={"action": "", "checksum": ""})

    assert "ctx" not in response.json()["detail"]
    assert "errors.pydantic.dev" not in response.text


def test_instance_is_the_path_without_the_query_string(client: TestClient) -> None:
    response = client.get("/audit/logs?skip=0&limit=10")

    assert response.json()["instance"] == "/audit/logs"


def test_domain_error_keeps_its_own_status_code(client: TestClient) -> None:
    response = client.get("/boom")

    assert response.status_code == 503
    assert response.json()["code"] == "AUDIT_STORAGE_ERROR"


def test_domain_error_detail_reaches_the_client_verbatim(client: TestClient) -> None:
    """El `detail` lo elige la capa que lanza, y las capas se ponen de acuerdo en
    pasar texto genérico (ver `AuditStorageError.default_detail`). Lo que el
    handler no debe hacer es añadir encima la causa, el tipo de excepción o un
    traceback."""
    response = client.get("/boom")
    body = response.json()

    assert body["detail"] == "the driver said something private"
    assert "AuditStorageError" not in response.text
    assert "Traceback" not in response.text


def test_unexpected_exception_becomes_a_500_problem(client: TestClient) -> None:
    response = client.get("/explode")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_unexpected_exception_does_not_leak_its_message(client: TestClient) -> None:
    response = client.get("/explode")

    assert "connection string with a password" not in response.text


def test_unexpected_exception_does_not_leak_a_traceback(client: TestClient) -> None:
    response = client.get("/explode")

    assert "RuntimeError" not in response.text


def test_unknown_route_is_a_404_problem(client: TestClient) -> None:
    response = client.get("/audit/logs/checksum/")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_wrong_verb_is_a_405_problem(client: TestClient) -> None:
    """Sólo se añade: `PUT`/`DELETE` no existen (SPEC §6.2)."""
    response = client.put("/audit/logs", json={})

    assert response.status_code == 405
    assert response.json()["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.parametrize(
    "method_path",
    [
        ("POST", "/audit/logs"),
        ("GET", "/audit/logs"),
        ("GET", "/boom"),
        ("GET", "/explode"),
        ("PUT", "/audit/logs"),
        ("DELETE", "/audit/logs"),
        ("GET", "/nope"),
    ],
)
def test_every_failure_above_300_returns_a_parseable_problem(
    client: TestClient, method_path: tuple[str, str]
) -> None:
    """La única regla dura del cliente de Go (`httpclient/client.go:39`): un cuerpo
    que pueda parsear, o el orquestador degrada a un error genérico y responde
    `502`."""
    method, path = method_path
    response = client.request(method, path, json={} if method != "GET" else None)

    body = json.loads(response.text)
    assert response.status_code >= 300
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert {"type", "title", "status", "detail"} <= set(body)
    assert body["status"] == response.status_code


@pytest.mark.parametrize(
    "method_path",
    [
        ("POST", "/audit/logs"),
        ("GET", "/audit/logs"),
        ("PUT", "/audit/logs"),
        ("GET", "/nope"),
    ],
)
def test_no_route_can_ever_answer_422(
    client: TestClient, method_path: tuple[str, str]
) -> None:
    """SPEC §7.3: si un `422` aparece alguna vez, es un defecto, no una variante."""
    method, path = method_path
    response = client.request(method, path, json={} if method != "GET" else None)

    assert response.status_code != 422


def test_openapi_does_not_advertise_a_422_response(client: TestClient) -> None:
    """FastAPI inyecta `422` en el esquema de toda ruta con cuerpo, salvo que la
    ruta declare `4XX` o `default` entre sus respuestas
    (`fastapi/openapi/utils.py`). El handler en ejecución no basta: un `422`
    documentado es el contrato mintiendo sobre lo que devuelve el servicio."""
    schema = client.get("/openapi.json").json()

    responses = schema["paths"]["/audit/logs"]["post"]["responses"]
    assert "422" not in responses
    assert "4XX" in responses


def test_every_response_status_is_mirrored_in_the_body(client: TestClient) -> None:
    """RFC 9457 §3.1 repite el estado en el cuerpo para que el documento sea
    autosuficiente; el cliente de Go lee ambos."""
    response = client.post("/audit/logs", json={"action": "pdf.extract"})

    assert response.json()["status"] == response.status_code == 400


def test_unmapped_framework_status_falls_back_to_a_500(client: TestClient) -> None:
    """Un estado fuera de la matriz se convierte en un `500` genérico en vez de un
    noveno `code`: el contrato tiene ocho filas e inventar una aquí lo haría
    divergir."""
    response = client.get("/teapot")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_not_found_is_reachable_as_a_domain_error() -> None:
    """El mapeo del handler necesita una clase de error real de la que tomar sus
    metadatos; afirmar el mapeo mantiene honestas las dos partes."""
    assert NotFoundError.status == 404
    assert ValidationError.status == 400
