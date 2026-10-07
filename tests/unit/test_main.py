"""Composition root.

Aquí se afirman dos propiedades que no se ven en ningún otro sitio, porque
ambas sólo se manifiestan cuando se rompen:

- `import app.main` no debe necesitar un entorno. `uvicorn app.main:create_app
  --factory` importa primero y llama a la fábrica después, así que un `Settings()`
  a nivel de módulo haría el servicio no importable en cualquier herramienta que
  lo inspeccione.
- Sin `SERVICE_API_TOKEN`, la fábrica se niega a construir la app. Eso convierte un
  orquestador mal configurado en un fallo de arranque en vez de una ristra de
  `401` que nadie lee (SPEC §2.5 H5).

También se afirma el orden del middleware: `add_middleware` antepone, así que el
último añadido es el más externo, y la autenticación tiene que ser la más externa
para ejecutarse antes del enrutado, del `415` y del `413` (SPEC §4.3).
"""

import importlib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.auth import BearerAuthMiddleware
from app.config import Settings
from app.errors import ServiceError
from app.main import create_app

TOKEN = "s3cr3t-shared-token"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in Settings.model_fields:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_API_TOKEN", TOKEN)


def test_app_main_imports_without_any_environment() -> None:
    """El módulo debe seguir importable sin nada configurado: importar un módulo
    no es lo mismo que arrancar un servicio."""
    module = importlib.import_module("app.main")

    assert callable(module.create_app)


def test_factory_refuses_to_build_the_app_without_a_token() -> None:
    with pytest.raises(ValidationError, match="service_api_token"):
        create_app()


def test_factory_refuses_to_build_the_app_with_a_blank_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVICE_API_TOKEN", "   ")

    with pytest.raises(ValidationError, match="service_api_token"):
        create_app()


def test_the_boot_error_never_contains_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Este error se imprime entero cuando el servicio se niega a arrancar."""
    monkeypatch.setenv("SERVICE_API_TOKEN", "   ")
    monkeypatch.setenv("APP_NAME", TOKEN)

    with pytest.raises(ValidationError) as failure:
        create_app()

    assert TOKEN not in str(failure.value)


def test_app_title_comes_from_the_configuration(configured: None) -> None:
    assert create_app().title == "Audit Log Microservice"


def test_settings_are_available_to_the_rest_of_the_app(configured: None) -> None:
    app = create_app()

    assert isinstance(app.state.settings, Settings)
    assert app.state.settings.service_api_token.get_secret_value() == TOKEN


def test_the_plain_token_is_unwrapped_exactly_once(
    configured: None,
) -> None:
    """La Capa 1 lo lee como string; nada más en el servicio llega a tener el
    valor sin cifrar."""
    app = create_app()

    assert app.state.api_token == TOKEN


def test_authentication_is_the_outermost_middleware(configured: None) -> None:
    app = create_app()

    assert app.user_middleware[0].cls is BearerAuthMiddleware


def test_exception_handlers_are_registered(configured: None) -> None:
    app = create_app()

    assert ServiceError in app.exception_handlers


def test_an_unauthenticated_request_is_refused(configured: None) -> None:
    client = TestClient(create_app(), raise_server_exceptions=False)

    assert client.get("/anything").status_code == 401


def test_an_authenticated_request_reaches_the_routes(configured: None) -> None:
    client = TestClient(create_app(), raise_server_exceptions=False)
    response = client.get("/anything", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 404
