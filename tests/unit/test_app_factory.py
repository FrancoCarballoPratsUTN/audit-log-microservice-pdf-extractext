"""Factory de la app: creación, token, middleware y handlers."""

import importlib
import logging
import signal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.auth import BearerAuthMiddleware
from app.config import Settings
from app.errors import ServiceError
from app.main import create_app

from tests.unit._main_common import TOKEN, clean_environment, configured


def test_app_main_imports_without_any_environment() -> None:
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


def test_invalid_log_level_fails_startup_with_a_clear_message(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "TRACE")
    with pytest.raises(ValidationError, match="log_level must be one of"):
        create_app()


def test_log_level_is_applied_on_each_create_app(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = logging.getLogger()
    original = root.level
    try:
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        create_app()
        assert root.level == logging.DEBUG
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        create_app()
        assert root.level == logging.ERROR
    finally:
        root.setLevel(original)


def test_the_boot_error_never_contains_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_the_plain_token_is_unwrapped_exactly_once(configured: None) -> None:
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
    def fail_if_installed(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("create_app must not install signal handlers")
    monkeypatch.setattr(signal, "signal", fail_if_installed)
    create_app()
