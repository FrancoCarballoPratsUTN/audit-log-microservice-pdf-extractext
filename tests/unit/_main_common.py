"""Ayudas comunes para probar el arranque."""

import pytest

from app.config import Settings

TOKEN = "s3cr3t-shared-token"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Limpia las variables de entorno de la prueba.

    Args:
        monkeypatch: Utilidad de pytest para sustituir valores.

    Returns:
        No retorna valor.
    """
    for variable in Settings.model_fields:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prepara una configuración válida para la prueba.

    Args:
        monkeypatch: Utilidad de pytest para sustituir valores.

    Returns:
        No retorna valor.
    """
    monkeypatch.setenv("SERVICE_API_TOKEN", TOKEN)
