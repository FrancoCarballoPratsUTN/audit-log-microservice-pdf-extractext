"""Pruebas del acceso mediante token."""

import ast
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import PUBLIC_PATHS, BearerAuthMiddleware, is_authorized
from app.api.exception_handlers import register_exception_handlers

TOKEN = "s3cr3t-shared-token"
PUBLIC_ENDPOINTS = ["/health", "/readyz", "/docs", "/openapi.json"]

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
    """Crea una aplicación de prueba con autenticación."""
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(BearerAuthMiddleware)
    app.state.api_token = TOKEN

    @app.get("/audit/logs")
    async def list_logs() -> dict[str, str]:
        """Crea una ruta de listado para la prueba."""
        return {"ok": "yes"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Crea una ruta de salud para la prueba."""
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        """Crea una ruta de disponibilidad para la prueba."""
        return {"status": "ok", "mongo": "ok"}

    return app


@pytest.fixture
def client() -> TestClient:
    """Crea un cliente para la aplicación de prueba."""
    return TestClient(build_app(), raise_server_exceptions=False)


@pytest.mark.parametrize("headers", UNAUTHORIZED_CASES)
def test_every_way_of_failing_authentication_is_a_401(
    client: TestClient, headers: dict[str, str]
) -> None:
    """Comprueba que toda forma de fallar la autenticación devuelve 401.

    Args:
        client: Cliente que usa la prueba.
        headers: Cabeceras HTTP.

    Returns:
        No retorna valor.
    """
    assert client.get("/audit/logs", headers=headers).status_code == 401


@pytest.mark.parametrize("headers", UNAUTHORIZED_CASES)
def test_the_answer_is_identical_in_all_four_cases(
    client: TestClient, headers: dict[str, str]
) -> None:
    """Si dos casos responden distinto, la diferencia le dice al atacante qué parte de
    la credencial estaba mal.

    Args:
        client: Cliente que usa la prueba.
        headers: Cabeceras HTTP.

    Returns:
        No retorna valor.
    """
    reference = client.get("/audit/logs", headers={"Authorization": "Bearer mal"})
    rejected = client.get("/audit/logs", headers=headers)

    assert rejected.json() == reference.json()
    assert rejected.headers["www-authenticate"] == reference.headers["www-authenticate"]


def test_the_response_is_a_problem_details_document(client: TestClient) -> None:
    """Comprueba que la respuesta usa el formato de problema.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        No retorna valor.
    """
    body = client.get("/audit/logs").json()

    assert body["code"] == "UNAUTHORIZED"
    assert body["status"] == 401
    assert body["type"] == "/problems/unauthorized"
    assert body["instance"] == "/audit/logs"


def test_the_challenge_header_names_the_scheme(client: TestClient) -> None:
    """Un `401` sin `WWW-Authenticate` deja al cliente adivinar cómo autenticarse.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        No retorna valor.
    """
    assert client.get("/audit/logs").headers["www-authenticate"] == "Bearer"


def test_a_valid_token_is_accepted(client: TestClient) -> None:
    """Comprueba que un token válido se acepta.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        No retorna valor.
    """
    response = client.get("/audit/logs", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200


@pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
def test_the_scheme_is_compared_case_insensitively(
    client: TestClient, scheme: str
) -> None:
    """El token de esquema no distingue mayúsculas.

    Args:
        client: Cliente que usa la prueba.
        scheme: Esquema de autenticación.

    Returns:
        No retorna valor.
    """
    response = client.get("/audit/logs", headers={"Authorization": f"{scheme} {TOKEN}"})

    assert response.status_code == 200


def test_a_credential_with_non_ascii_characters_is_rejected() -> None:
    """Comprueba que una credencial con caracteres no ASCII se rechaza."""
    assert not is_authorized("Bearer señal", TOKEN)


def test_a_token_with_non_ascii_characters_is_accepted() -> None:
    """Comprueba que un token con caracteres no ASCII se acepta."""
    assert is_authorized("Bearer señal-segura-ñ", "señal-segura-ñ")


def test_neither_the_token_nor_the_credential_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Comprueba que no se registran el token ni la credencial.

    Args:
        caplog: Capturador de registros de pytest.

    Returns:
        No retorna valor.
    """
    caplog.set_level(logging.INFO)
    is_authorized("Bearer señal", TOKEN)

    assert "señal" not in caplog.text
    assert TOKEN not in caplog.text


def test_the_token_value_is_compared_case_sensitively(client: TestClient) -> None:
    """El esquema es una palabra clave; el valor es una credencial. Pasarlo a mayúsculas
    no debe autenticar.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        No retorna valor.
    """
    response = client.get(
        "/audit/logs", headers={"Authorization": f"Bearer {TOKEN.upper()}"}
    )

    assert response.status_code == 401


@pytest.mark.parametrize("path", PUBLIC_ENDPOINTS)
def test_public_paths_answer_without_credentials(client: TestClient, path: str) -> None:
    """Comprueba que las rutas públicas responden sin credenciales.

    Args:
        client: Cliente que usa la prueba.
        path: Ruta de la petición.

    Returns:
        No retorna valor.
    """
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", PUBLIC_ENDPOINTS)
def test_public_paths_are_declared(client: TestClient, path: str) -> None:
    """Comprueba que las rutas públicas están declaradas.

    Args:
        client: Cliente que usa la prueba.
        path: Ruta de la petición.

    Returns:
        No retorna valor.
    """
    assert path in PUBLIC_PATHS


def test_unknown_paths_also_require_authentication(client: TestClient) -> None:
    """Cerrado por defecto: un path que nadie declaró público no debe convertirse en una
    puerta abierta por omisión.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        No retorna valor.
    """
    assert client.get("/does-not-exist").status_code == 401


def test_the_presented_token_never_appears_in_the_response(client: TestClient) -> None:
    """Comprueba que el token presentado no aparece en la respuesta.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        No retorna valor.
    """
    response = client.get(
        "/audit/logs", headers={"Authorization": "Bearer token-incorrecto"}
    )

    assert "token-incorrecto" not in response.text


def test_the_configured_token_never_appears_in_the_response(client: TestClient) -> None:
    """Comprueba que el token configurado no aparece en la respuesta.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        No retorna valor.
    """
    response = client.get("/audit/logs")

    assert TOKEN not in response.text


def test_a_missing_token_beats_a_missing_route(client: TestClient) -> None:
    """La autenticación se ejecuta antes del enrutado, así que un sondeo sin
    credenciales no puede mapear la superficie de la API.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        No retorna valor.
    """
    assert client.get("/audit/logs/checksum/").status_code == 401


def test_the_credential_is_compared_in_constant_time() -> None:
    """Una comparación en tiempo constante no se puede observar desde fuera: cambiar
    `secrets.compare_digest` por `==` deja verdes todos los demás tests,...
    """
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
    """Comprueba que la credencial no se compara con el operador de igualdad."""
    source = Path(__file__).resolve().parents[3] / "app" / "api" / "auth.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    comparisons = {
        type(node.ops[0]).__name__
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.Eq)
    }

    assert not comparisons, "comparar la credencial con == filtra su longitud"
