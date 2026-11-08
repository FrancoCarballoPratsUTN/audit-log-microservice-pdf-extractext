"""Comunes para los tests de `app.main` (divididos de test_main.py).

Fixtures y constantes compartidas por los tres módulos de test. No se recolecta
como test por empezar con guion bajo.
"""

import logging
import signal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

TOKEN = "s3cr3t-shared-token"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in Settings.model_fields:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_API_TOKEN", TOKEN)
