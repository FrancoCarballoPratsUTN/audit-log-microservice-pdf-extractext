"""Pruebas del arranque y cierre del servicio."""
import signal
from pathlib import Path

import pytest

from app.main import create_app, lifespan
from tests.fakes.fake_mongo import WorkingClient, WorkingCollection
from tests.unit._main_common import TOKEN  # noqa: F401


async def test_shutdown_deregisters_consul_and_closes_the_client_once(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comprueba que el cierre desregistra Consul y cierra el cliente una vez.

    Args:
        configured: Configuración de prueba ya preparada.
        monkeypatch: Utilidad de pytest para sustituir valores.

    Returns:
        No retorna valor.
    """
    app = create_app()
    calls: list[str] = []

    class RecordingClient:
        def __init__(self) -> None:
            """Crea un cliente que registra su cierre."""
            self.close_calls = 0

        async def close(self) -> None:
            """Registra que el cliente se cerró."""
            self.close_calls += 1

    client = RecordingClient()

    async def noop(*_args: object, **_kwargs: object) -> None:
        """No hace nada.

        Args:
            *_args: Argumentos adicionales.
            **_kwargs: Argumentos adicionales.

        Returns:
            No retorna valor.
        """
        return None

    def fail_if_installed(*_args: object, **_kwargs: object) -> None:
        """Falla si se intenta instalar un manejador de señales.

        Args:
            *_args: Argumentos adicionales.
            **_kwargs: Argumentos adicionales.

        Returns:
            No retorna valor.
        """
        raise AssertionError("the lifespan must not install signal handlers")

    monkeypatch.setattr(
        "app.main.consul_registration",
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
    monkeypatch.setattr("app.main.ReadinessProbe", lambda *_args, **_kwargs: noop)
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
        monkeypatch.setattr(signal, "signal", original_signal)
    assert calls == ["register", "deregister"]
    assert client.close_calls == 1


async def test_deregistration_failure_is_logged_and_shutdown_continues(
    configured: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Comprueba que un fallo al desregistrar se registra y el cierre continúa.

    Args:
        configured: Configuración de prueba ya preparada.
        monkeypatch: Utilidad de pytest para sustituir valores.
        caplog: Capturador de registros de pytest.

    Returns:
        No retorna valor.
    """
    app = create_app()

    class RecordingClient:
        def __init__(self) -> None:
            """Crea un cliente que registra su cierre."""
            self.close_calls = 0

        async def close(self) -> None:
            """Registra que el cliente se cerró."""
            self.close_calls += 1

    client = RecordingClient()

    async def noop(*_args: object, **_kwargs: object) -> None:
        """No hace nada.

        Args:
            *_args: Argumentos adicionales.
            **_kwargs: Argumentos adicionales.

        Returns:
            No retorna valor.
        """
        return None

    monkeypatch.setattr(
        "app.main.consul_registration",
        lambda: {
            "address": "http://consul:8500",
            "token": "consul-token",
            "ca_file": None,
            "service_id": "auditlog-1",
        },
    )
    monkeypatch.setattr("app.main.open_client", lambda _settings: client)
    monkeypatch.setattr("app.main.audit_logs_collection", lambda *_args: object())
    monkeypatch.setattr("app.main.ReadinessProbe", lambda *_args, **_kwargs: noop)
    monkeypatch.setattr("app.main.register_service", lambda **_kwargs: None)

    def fail_deregister(*_args: object, **_kwargs: object) -> None:
        """Lanza un error al intentar desregistrar el servicio.

        Args:
            *_args: Argumentos adicionales.
            **_kwargs: Argumentos adicionales.

        Returns:
            No retorna valor.
        """
        raise RuntimeError("consul down")

    monkeypatch.setattr("app.main.deregister_service", fail_deregister)
    async with lifespan(app):
        pass
    assert client.close_calls == 1
    assert "Consul service deregistration failed." in caplog.text


async def test_lifespan_builds_the_collection_once(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comprueba que el ciclo de vida crea la colección una sola vez.

    Args:
        configured: Configuración de prueba ya preparada.
        monkeypatch: Utilidad de pytest para sustituir valores.

    Returns:
        No retorna valor.
    """
    collection = WorkingCollection()
    built: list[object] = []

    def build_collection(*_args: object) -> object:
        """Crea una colección falsa y cuenta las llamadas.

        Args:
            *_args: Argumentos adicionales.

        Returns:
            El objeto creado para la prueba.
        """
        built.append(collection)
        return collection

    monkeypatch.setattr("app.main.open_client", lambda _settings: WorkingClient())
    monkeypatch.setattr("app.main.audit_logs_collection", build_collection)
    async with lifespan(create_app()):
        pass
    assert built == [collection]


def test_the_container_disables_uvicorns_access_log() -> None:
    """Comprueba que el contenedor desactiva el registro de Uvicorn."""
    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile"
    assert "--no-access-log" in dockerfile.read_text(encoding="utf-8")
