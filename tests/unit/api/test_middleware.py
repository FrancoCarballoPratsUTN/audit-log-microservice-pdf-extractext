"""Middlewares de transporte: orden real, forma de la respuesta y observabilidad.

El orden del *stack* es el contrato (SPEC §4.3): `401` antes de `415`, `415`
antes de `413`, y `413` antes del `400` de la validación de Pydantic. Este
archivo lo fija de dos maneras: mirando `app.user_middleware` —el orden real que
construye la fábrica, no el que la prosa describe— y provocando cada rechazo con
una petición, que es lo que el cliente observa.

La decisión que unifica todo: `RequestIdMiddleware` corre **por fuera** de los
límites, para que un `415`, un `413` y hasta un `400` viajen con su
`X-Request-ID` y puedan correlacionarse en el log. `CORS` queda por **dentro** de
la autenticación, así que un *preflight* a una ruta protegida sigue siendo `401`:
el cliente Go no navega, y una petición sin credencial no debe recibir respuesta
de ningún tipo (SPEC §4.3).

La prueba de que el límite de body **no lee** el cuerpo se hace sobre el código
fuente, como `test_auth.py` con `compare_digest`: que no lea el cuerpo es una
propiedad de implementación que ningún test de caja negra puede ver —un body
pequeño con `Content-Length` grande y viceversa se comportan igual de bien si el
servidor lo lee—.
"""

import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from app.api.auth import BearerAuthMiddleware
from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    ContentTypeMiddleware,
    RequestIdMiddleware,
    install_middleware,
    parse_content_length,
)
from app.config import Settings
from app.main import create_app

TOKEN = "s3cr3t-shared-token"
LIMIT = 64
AUTH = {"Authorization": f"Bearer {TOKEN}"}
JSON = {"Content-Type": "application/json"}
MIDDLEWARE_SOURCE = (
    Path(__file__).resolve().parents[3] / "app" / "api" / "middleware.py"
)

EXPECTED_ORDER = [
    BearerAuthMiddleware,
    RequestIdMiddleware,
    ContentTypeMiddleware,
    BodySizeLimitMiddleware,
    CORSMiddleware,
    AccessLogMiddleware,
]


class Payload(BaseModel):
    """Cuerpo mínimo: obliga a FastAPI a parsear el body, para poder observar el
    `400` que queda *después* de `415` y `413`."""

    action: str = "pdf.extract"


def build_app(*, max_body_bytes: int = LIMIT) -> FastAPI:
    """App mínima con el stack real, sin Mongo: el rechazo ocurre antes de la
    ruta, así que no hace falta el servicio."""
    app = FastAPI()
    register_exception_handlers(app)
    app.state.api_token = TOKEN
    install_middleware(app, max_body_bytes=max_body_bytes)

    @app.post("/audit/logs", status_code=201)
    async def create(payload: Payload) -> dict[str, str]:
        return {"action": payload.action}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in Settings.model_fields:
        monkeypatch.delenv(variable, raising=False)


def test_the_stack_order_is_the_contract_order() -> None:
    app = build_app()

    assert [middleware.cls for middleware in app.user_middleware] == EXPECTED_ORDER


def test_the_factory_builds_the_same_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    """El orden se resuelve en un único sitio: `install_middleware`. La fábrica
    no puede divergir de la app de pruebas."""
    monkeypatch.setenv("SERVICE_API_TOKEN", TOKEN)

    app = create_app()

    assert [middleware.cls for middleware in app.user_middleware] == EXPECTED_ORDER


def test_authentication_beats_every_other_check(client: TestClient) -> None:
    """Sin token, un body enorme y `text/plain` a la vez: gana el `401`. No se
    parsea ni se limita el body de quien no está autenticado (SPEC §4.3)."""
    response = client.post(
        "/audit/logs",
        headers={"Content-Type": "text/plain"},
        content=b"x" * (LIMIT + 1),
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_content_type_is_checked_before_body_size(client: TestClient) -> None:
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": "text/plain"},
        content=b"x" * (LIMIT + 1),
    )

    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_body_size_is_checked_before_validation(client: TestClient) -> None:
    response = client.post(
        "/audit/logs", headers={**AUTH, **JSON}, content=b"x" * (LIMIT + 1)
    )

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_validation_is_the_last_gate(client: TestClient) -> None:
    """Con token, `application/json` y body pequeño, el fallo que queda es el de
    estructura: `400`, nunca el `422` de FastAPI (SPEC §3.3 D1)."""
    accepted = client.post(
        "/audit/logs", headers={**AUTH, **JSON}, content=b'{"action":"pdf.extract"}'
    )
    rejected = client.post("/audit/logs", headers={**AUTH, **JSON}, content=b"{nope")

    assert accepted.status_code == 201
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/xml", "application/json-patch+json", ""],
    ids=["text/plain", "xml", "json-patch", "ausente"],
)
def test_post_without_json_content_type_is_415(
    client: TestClient, content_type: str
) -> None:
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": content_type},
        content=b"{}",
    )

    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_a_json_content_type_with_parameters_is_accepted(client: TestClient) -> None:
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": "application/json; charset=utf-8"},
        content=b'{"action":"pdf.extract"}',
    )

    assert response.status_code == 201


def test_a_get_does_not_require_a_content_type(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_an_incoming_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "3f2a91c8e7b4d05a"})

    assert response.headers["x-request-id"] == "3f2a91c8e7b4d05a"


def test_a_missing_request_id_is_generated(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["x-request-id"]


def test_a_blank_request_id_is_regenerated(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "   "})

    request_id = response.headers["x-request-id"]
    assert request_id.strip() == request_id
    assert request_id != ""


def test_the_request_id_survives_a_rejected_request(client: TestClient) -> None:
    """La razón de que `RequestId` corra por fuera del `415`: un rechazo también
    debe poder correlacionarse con su petición."""
    response = client.post(
        "/audit/logs",
        headers={**AUTH, "Content-Type": "text/plain", "X-Request-ID": "trace-me"},
        content=b"{}",
    )

    assert response.status_code == 415
    assert response.headers["x-request-id"] == "trace-me"


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
    """`Content-Length` ausente o ilegible cuenta como 0, no revienta (AC de T14)."""
    assert parse_content_length(value) == expected


def test_the_body_limit_never_reads_the_body() -> None:
    """El límite decide con `Content-Length`, así que una subida enorme no entra
    en memoria. Ningún test de caja negra lo puede ver: un body grande y otro
    pequeño se comportan igual si el servidor lo lee. Por eso se mira el fuente."""
    source = MIDDLEWARE_SOURCE.read_text(encoding="utf-8")

    for reader in (".body(", ".stream(", "request.json", "request.data", ".form("):
        assert reader not in source, f"el límite de body no debe usar {reader}"


def test_cors_answers_a_preflight(client: TestClient) -> None:
    """Starlette responde `200` a un preflight válido; se anota en el test en vez
    de envolver la librería (AC de T14)."""
    response = client.options(
        "/health",
        headers={
            "Origin": "https://example.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_a_cross_origin_response_advertises_the_allowed_origin(
    client: TestClient,
) -> None:
    response = client.get("/health", headers={"Origin": "https://example.test"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_cors_cannot_open_a_protected_route_without_a_token(
    client: TestClient,
) -> None:
    """CORS vive por dentro de auth: el preflight de una ruta protegida sigue
    siendo `401`."""
    response = client.options(
        "/audit/logs",
        headers={
            "Origin": "https://example.test",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 401


def test_the_access_log_records_method_path_status_and_duration(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        client.get("/health")

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "GET /health" in message and "200" in message and "ms" in message
        for message in messages
    )


def test_the_access_log_carries_the_request_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        client.get("/health", headers={"X-Request-ID": "trace-me"})

    assert any("trace-me" in record.getMessage() for record in caplog.records)


def test_an_unhandled_error_is_logged_and_becomes_a_500(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.api.middleware"):
        response = client.get("/boom", headers=AUTH)

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert any("boom" in record.getMessage() for record in caplog.records)
