"""Configuración y registro de Consul."""

import pytest

from app.bootstrap.consul import (
    consul_registration as _consul_registration,
)
from app.bootstrap.consul import (
    settings_from_environment_or_consul as _settings_from_environment_or_consul,
)
from tests.unit._main_common import TOKEN


def test_consul_configuration_is_loaded_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONSUL_ENABLED", "true")
    monkeypatch.setenv("CONSUL_HTTP_ADDR", "http://consul:8500")
    monkeypatch.setenv("CONSUL_HTTP_TOKEN", "consul-token")
    monkeypatch.setenv("CONSUL_KV_PREFIX", "app/auditlog")
    monkeypatch.setattr(
        "app.bootstrap.consul.load_prefix",
        lambda *_args, **_kwargs: {"SERVICE_API_TOKEN": TOKEN},
    )
    settings = _settings_from_environment_or_consul()
    assert settings.service_api_token.get_secret_value() == TOKEN


def test_consul_registration_builds_the_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONSUL_ENABLED", "true")
    monkeypatch.setenv("CONSUL_HTTP_ADDR", "http://consul:8500")
    monkeypatch.setenv("CONSUL_HTTP_TOKEN", "consul-token")
    monkeypatch.setenv("CONSUL_SERVICE_ADDRESS", "auditlog-1")
    monkeypatch.setenv("CONSUL_SERVICE_PORT", "9000")
    monkeypatch.setenv("CONSUL_SERVICE_NAME", "auditlog")
    monkeypatch.setenv("CONSUL_SERVICE_ID", "auditlog-1")
    monkeypatch.setenv("CONSUL_SERVICE_TAGS", "security-headers@file; ;audit-cb@file")
    monkeypatch.delenv("CONSUL_HTTP_CA_FILE", raising=False)
    assert _consul_registration() == {
        "address": "http://consul:8500",
        "token": "consul-token",
        "ca_file": None,
        "service_id": "auditlog-1",
        "service_name": "auditlog",
        "service_address": "auditlog-1",
        "service_port": 9000,
        "check_url": "http://auditlog-1:9000/readyz",
        "tags": ["security-headers@file", "audit-cb@file"],
    }
