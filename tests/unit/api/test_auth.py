"""Autenticación por token Bearer.

Cuatro maneras de fallar, una sola respuesta. El `detail` es idéntico para un
token ausente, un valor vacío, un esquema ajeno y un valor incorrecto, a
propósito: distinguirlos le daría a un atacante un oráculo para adivinar
credenciales (SPEC §4.2).

La comparación es `secrets.compare_digest` porque `==` sobre strings corta en el
primer byte distinto, y el tiempo que tarda filtraría cuántos caracteres
iniciales son correctos.

`/health` y `/readyz` quedan abiertas: los sondeos de la plataforma no pueden
llevar credenciales, y un servicio que responde `401` a su propio chequeo de
vivacidad es un servicio al que matan.
"""

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import PUBLIC_PATHS, BearerAuthMiddleware
from app.api.exception_handlers import register_exception_handlers

TOKEN = "s3cr3t-shared-token"

UNAUTHORIZED_CASES = [
    pytest.param({}, id="sin cabecera"),
    pytest.param({"Authorization": ""}, id="cabecera vacía"),
    pytest.param({"Authorization": "Bearer"}, id="esquema sin valor"),
    pytest.param({"Authorization": "Bearer   "}, id="esquema con valor en blanco"),
    pytest.param({"Authorization": "Basic dXNlcjpwYXNz"}, id="esquema ajeno"),
    pytest.param({"Authorization": "Bearer token-incorrecto"}, id="valor incorrecto"),
    pytest.param({"Authorization": "Bearer " + TOKEN + "x"}, id="token con sufijo"),
]


def build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(BearerAuthMiddleware)
    app.state.api_token = TOKEN

    @app.get("/audit/logs")
    async def list_logs() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        return {"status": "ok", "mongo": "ok"}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


@pytest.mark.parametrize("headers", UNAUTHORIZED_CASES)
def test_every_way_of_failing_authentication_is_a_401(
    client: TestClient, headers: dict[str, str]
) -> None:
    assert client.get("/audit/logs", headers=headers).status_code == 401


@pytest.mark.parametrize("headers", UNAUTHORIZED_CASES)
def test_the_answer_is_identical_in_all_four_cases(
    client: TestClient, headers: dict[str, str]
) -> None:
    """La comprobación del oráculo: si dos casos responden distinto, la diferencia
    le dice al atacante qué parte de la credencial estaba mal."""
    reference = client.get("/audit/logs", headers={"Authorization": "Bearer mal"})
    rejected = client.get("/audit/logs", headers=headers)

    assert rejected.json() == reference.json()
    assert rejected.headers["www-authenticate"] == reference.headers["www-authenticate"]


def test_the_response_is_a_problem_details_document(client: TestClient) -> None:
    body = client.get("/audit/logs").json()

    assert body["code"] == "UNAUTHORIZED"
    assert body["status"] == 401
    assert body["type"] == "/problems/unauthorized"
    assert body["instance"] == "/audit/logs"


def test_the_challenge_header_names_the_scheme(client: TestClient) -> None:
    """RFC 9110 §15.5.2: un `401` sin `WWW-Authenticate` deja al cliente adivinar
    cómo autenticarse."""
    assert client.get("/audit/logs").headers["www-authenticate"] == "Bearer"


def test_a_valid_token_is_accepted(client: TestClient) -> None:
    response = client.get("/audit/logs", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200


@pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
def test_the_scheme_is_compared_case_insensitively(
    client: TestClient, scheme: str
) -> None:
    """RFC 9110 §5.1: el token de esquema no distingue mayúsculas."""
    response = client.get("/audit/logs", headers={"Authorization": f"{scheme} {TOKEN}"})

    assert response.status_code == 200


def test_the_token_value_is_compared_case_sensitively(client: TestClient) -> None:
    """El esquema es una palabra clave; el valor es una credencial. Pasarlo a
    mayúsculas no debe autenticar."""
    response = client.get(
        "/audit/logs", headers={"Authorization": f"Bearer {TOKEN.upper()}"}
    )

    assert response.status_code == 401


@pytest.mark.parametrize("path", ["/health", "/readyz"])
def test_probes_answer_without_credentials(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/health", "/readyz"])
def test_probes_are_declared_public(client: TestClient, path: str) -> None:
    assert path in PUBLIC_PATHS


def test_unknown_paths_also_require_authentication(client: TestClient) -> None:
    """Cerrado por defecto: un path que nadie declaró público no debe convertirse
    en una puerta abierta por omisión."""
    assert client.get("/does-not-exist").status_code == 401


def test_the_presented_token_never_appears_in_the_response(client: TestClient) -> None:
    response = client.get(
        "/audit/logs", headers={"Authorization": "Bearer token-incorrecto"}
    )

    assert "token-incorrecto" not in response.text


def test_the_configured_token_never_appears_in_the_response(client: TestClient) -> None:
    response = client.get("/audit/logs")

    assert TOKEN not in response.text


def test_a_missing_token_beats_a_missing_route(client: TestClient) -> None:
    """La autenticación se ejecuta antes del enrutado, así que un sondeo sin
    credenciales no puede mapear la superficie de la API."""
    assert client.get("/audit/logs/checksum/").status_code == 401


def test_the_credential_is_compared_in_constant_time() -> None:
    """Una comparación en tiempo constante no se puede observar desde fuera:
    cambiar `secrets.compare_digest` por `==` deja verdes todos los demás tests,
    porque `==` para en el primer byte distinto y la diferencia sólo asoma en el
    tiempo. Por eso esta guarda lee el fuente, igual que
    `tests/unit/test_package_layout.py` vigila la dirección de las dependencias."""
    source = Path(__file__).resolve().parents[3] / "app" / "api" / "auth.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "compare_digest" in called, (
        "la credencial bearer debe compararse con secrets.compare_digest"
    )


def test_the_credential_is_never_compared_with_the_equality_operator() -> None:
    source = Path(__file__).resolve().parents[3] / "app" / "api" / "auth.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    comparisons = {
        type(node.ops[0]).__name__
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.Eq)
    }

    assert not comparisons, "comparar la credencial con == filtra su longitud"
