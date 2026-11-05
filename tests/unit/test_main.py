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
import signal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.auth import BearerAuthMiddleware
from app.config import Settings
from app.errors import ServiceError
from app.main import create_app, lifespan

TOKEN = "s3cr3t-shared-token"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in Settings.model_fields:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


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


def test_create_app_does_not_install_process_signal_handlers(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uvicorn es el dueño de SIGTERM/SIGINT.

    El servicio no debe reemplazar el handler que uvicorn instala para drenar
    las conexiones: si lo hiciera, el apagado graceful dejaría de ocurrir o
    ocurriría en un orden distinto al que el servidor garantiza.
    """

    def fail_if_installed(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("create_app must not install signal handlers")

    monkeypatch.setattr(signal, "signal", fail_if_installed)

    create_app()


async def test_shutdown_deregisters_consul_and_closes_the_client_once(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El cierre pertenece al `finally` del lifespan, no a una señal.

    Con Consul habilitado, el apagado debe deregistrar el servicio y cerrar el
    cliente exactamente una vez. El doble de `signal.signal` falla si el código
    intenta apropiarse del handler del proceso.
    """
    app = create_app()
    calls: list[str] = []

    class RecordingClient:
        def __init__(self) -> None:
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

    client = RecordingClient()

    async def noop(*_args: object, **_kwargs: object) -> None:
        return None

    def fail_if_installed(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the lifespan must not install signal handlers")

    monkeypatch.setattr(
        "app.main._consul_registration",
        lambda: {
            "address": "http://consul:8500",
            "token": "consul-token",
            "ca_file": None,
            "service_id": "auditlog-1",
            "service_name": "auditlog",
            "service_address": "auditlog-1",
            "service_port": 8000,
            "check_url": "http://auditlog-1:8000/readyz",
            "tags": [],
        },
    )
    monkeypatch.setattr("app.main.open_client", lambda _settings: client)
    monkeypatch.setattr("app.main.audit_logs_collection", lambda *_args: object())
    monkeypatch.setattr("app.main.ping", noop)
    monkeypatch.setattr("app.main.ensure_indexes", noop)
    monkeypatch.setattr(
        "app.main.register_service", lambda **_kwargs: calls.append("register")
    )
    monkeypatch.setattr(
        "app.main.deregister_service",
        lambda *_args, **_kwargs: calls.append("deregister"),
    )
    original_signal = signal.signal
    monkeypatch.setattr(signal, "signal", fail_if_installed)
    try:
        async with lifespan(app):
            pass
    finally:
        # pytest-asyncio restaura SIGINT al terminar el test; dejar el doble
        # instalado durante ese teardown haría fallar el propio runner.
        monkeypatch.setattr(signal, "signal", original_signal)

    assert calls == ["register", "deregister"]
    assert client.close_calls == 1
