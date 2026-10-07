"""Configuración del servicio.

Dos decisiones de este módulo valen más que el resto:

- `SERVICE_API_TOKEN` **no tiene default**. Si falta, `Settings()` lanza y la
  app no arranca. Un token ausente entre el Orquestador y AUDA se convierte así
  en un fallo de arranque, no en una cadena de `401` que nadie ve (SPEC §2.5 H5).
- Los límites numéricos exigen un valor **mayor que cero**, salvo
  `RETENTION_DAYS`, donde `0` significa "retención desactivada". Un timeout o un
  límite en `0` desactivaría la protección en silencio, que es peor que no
  tenerla.
"""

import os

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings, get_settings

TOKEN = "s3cr3t-shared-token"
BASE_ENVIRON = {"SERVICE_API_TOKEN": TOKEN}


def build_settings(**overrides: object) -> Settings:
    """Ajustes sobre el mínimo válido, sin mutar el proceso."""
    return get_settings(environ={**BASE_ENVIRON, **overrides})


def test_defaults_match_the_spec() -> None:
    settings = build_settings()

    assert settings.app_name == "Audit Log Microservice"
    assert settings.mongo_uri == "mongodb://localhost:27017"
    assert settings.mongo_database == "pdf_extractext_audit"
    assert settings.mongo_audit_logs_collection == "audit_logs"
    assert settings.mongo_timeout_ms == 5000
    assert settings.max_body_bytes == 1048576
    assert settings.max_details_bytes == 65536
    assert settings.default_limit == 10
    assert settings.max_limit == 100
    assert settings.max_skip == 10000
    assert settings.retention_days == 0


def test_token_is_read_from_the_environment() -> None:
    assert build_settings().service_api_token.get_secret_value() == TOKEN


def test_missing_token_is_rejected() -> None:
    with pytest.raises(ValidationError, match="service_api_token"):
        get_settings(environ={})


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_token_counts_as_missing(blank: str) -> None:
    """Un token de espacios no protege nada, y aceptarlo arrancaría el servicio
    con una credencial que nadie puede acertar."""
    with pytest.raises(ValidationError, match="service_api_token"):
        get_settings(environ={"SERVICE_API_TOKEN": blank})


def test_missing_token_error_never_prints_a_token() -> None:
    """El error de arranque se imprime entero en consola: si incluyera el valor,
    un token rotado a medias acabaría en los logs del despliegue."""
    try:
        get_settings(environ={"SERVICE_API_TOKEN": "  "})
    except ValidationError as exc:
        rendered = str(exc)
    else:
        pytest.fail("un token en blanco debe rechazarse")

    assert TOKEN not in rendered
    assert "s3cr3t" not in rendered


def test_token_is_never_exposed_by_the_representation() -> None:
    """`SecretStr` se enmascara en `repr` y en `str`, así que un
    `logger.info("%s", settings)` no filtra la credencial."""
    settings = build_settings()

    assert TOKEN not in repr(settings)
    assert TOKEN not in str(settings)


def test_token_is_a_secret_string() -> None:
    assert isinstance(build_settings().service_api_token, SecretStr)


@pytest.mark.parametrize(
    "field",
    [
        "mongo_timeout_ms",
        "max_body_bytes",
        "max_details_bytes",
        "default_limit",
        "max_limit",
        "max_skip",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_limits_reject_zero_and_negative_values(field: str, value: int) -> None:
    """`0` en un límite no significa "sin límite": significa que la comprobación
    nunca dispara."""
    with pytest.raises(ValidationError, match=field):
        build_settings(**{field: value})


def test_retention_accepts_zero_because_it_means_disabled() -> None:
    assert build_settings(retention_days="0").retention_days == 0


def test_retention_rejects_negative_days() -> None:
    with pytest.raises(ValidationError, match="retention_days"):
        build_settings(retention_days="-1")


def test_non_numeric_limit_is_rejected_naming_the_variable() -> None:
    with pytest.raises(ValidationError, match="mongo_timeout_ms"):
        build_settings(mongo_timeout_ms="pronto")


def test_overrides_replace_the_defaults() -> None:
    settings = build_settings(max_limit="25", mongo_database="otro")

    assert settings.max_limit == 25
    assert settings.mongo_database == "otro"


def test_unknown_variables_are_ignored() -> None:
    """El proceso que lanza el servicio carga su propio entorno; que una
    variable ajena no tumbe el arranque no es negociable."""
    assert build_settings(OTRA_VARIABLE="x").app_name == "Audit Log Microservice"


def test_environ_argument_does_not_mutate_the_process() -> None:
    before = dict(os.environ)

    build_settings(max_limit="42")

    assert dict(os.environ) == before


def test_environ_argument_does_not_leak_into_the_next_call() -> None:
    build_settings(max_limit="42", service_api_token=TOKEN)

    with pytest.raises(ValidationError):
        get_settings(environ={})


def test_reads_the_real_environment_when_no_mapping_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVICE_API_TOKEN", "from-the-process")
    monkeypatch.setenv("MAX_LIMIT", "7")

    settings = get_settings()

    assert settings.service_api_token.get_secret_value() == "from-the-process"
    assert settings.max_limit == 7


def test_settings_exposes_every_variable_of_the_spec() -> None:
    """Doce variables en SPEC §3.6. Una ausente aquí es una variable que nadie
    puede configurar."""
    expected = {
        "app_name",
        "service_api_token",
        "mongo_uri",
        "mongo_database",
        "mongo_audit_logs_collection",
        "mongo_timeout_ms",
        "max_body_bytes",
        "max_details_bytes",
        "default_limit",
        "max_limit",
        "max_skip",
        "retention_days",
    }

    assert expected <= set(Settings.model_fields)
