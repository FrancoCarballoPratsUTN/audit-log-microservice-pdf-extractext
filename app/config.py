"""Configuración del servicio: se lee una vez al arrancar del entorno.

`SERVICE_API_TOKEN` no tiene default: sin él el servicio se niega a arrancar
(SPEC §3.6). El token es `SecretStr` para que nunca filtre por `repr` ni logs.
"""

import os
from collections.abc import Mapping
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.consul import load_prefix

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class Settings(BaseSettings):
    """Configuración de ejecución del servicio de auditoría."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Audit Log Microservice"
    log_level: str = "INFO"
    service_api_token: SecretStr
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_database: str = "pdf_extractext_audit"
    mongo_audit_logs_collection: str = "audit_logs"
    mongo_timeout_ms: int = Field(default=5000, gt=0)
    max_body_bytes: int = Field(default=1048576, gt=0)
    max_details_bytes: int = Field(default=65536, gt=0)
    default_limit: int = Field(default=10, gt=0)
    max_limit: int = Field(default=100, gt=0)
    max_skip: int = Field(default=10000, gt=0)
    retention_days: int = Field(default=0, ge=0)

    @field_validator("service_api_token")
    @classmethod
    def reject_blank_token(cls, token: SecretStr) -> SecretStr:
        """Tratar como ausente un token formado sólo por espacios."""
        if not token.get_secret_value().strip():
            raise ValueError(
                "service_api_token must not be empty: generate one with "
                "'python -c \"import secrets; print(secrets.token_urlsafe(32))\"'"
            )
        return token

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        """Validar el nivel de log al arrancar, no en el import."""
        if not isinstance(value, str):
            return value
        level = value.strip().upper()
        if level not in LOG_LEVELS:
            raise ValueError(
                f"log_level must be one of {', '.join(LOG_LEVELS)} (got {value!r})"
            )
        return level

    @model_validator(mode="after")
    def validate_related_limits(self) -> Self:
        """Las parejas de límites deben ser coherentes entre sí."""
        if self.default_limit > self.max_limit:
            raise ValueError(
                "default_limit must be less than or equal to max_limit "
                f"(default_limit={self.default_limit} > max_limit={self.max_limit})"
            )
        if self.max_details_bytes > self.max_body_bytes:
            raise ValueError(
                "max_details_bytes must be less than or equal to max_body_bytes "
                f"(max_details_bytes={self.max_details_bytes} > "
                f"max_body_bytes={self.max_body_bytes})"
            )
        return self


def get_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Construir la configuración desde el entorno (o un Mapping para tests).

    Nunca se llama a nivel de módulo: importar `app.config` no exige entorno.

    Args:
        environ: Variables de entorno explícitas. Si se omite, se leen
            `os.environ` y `.env`; si se aporta, se ignora `.env`.

    Returns:
        La configuración validada.

    Raises:
        ValidationError: Si falta el token, un límite no es positivo, o una
            pareja de límites es incoherente.
    """
    if environ is None:
        return Settings()
    return Settings(
        _env_file=None,
        **{key.lower(): value for key, value in environ.items()},
    )


def load_settings() -> Settings:
    """Resolver la configuración desde el entorno o desde Consul.

    Cuando `CONSUL_ENABLED=true`, lee las claves del prefix KV de Consul;
    de lo contrario, lee del entorno y del archivo `.env`.
    """
    if os.getenv("CONSUL_ENABLED", "").lower() != "true":
        return get_settings()
    values = load_prefix(
        os.getenv("CONSUL_HTTP_ADDR", ""),
        os.getenv("CONSUL_HTTP_TOKEN", ""),
        os.getenv("CONSUL_KV_PREFIX", ""),
        ca_file=os.getenv("CONSUL_HTTP_CA_FILE"),
    )
    return get_settings(values)
