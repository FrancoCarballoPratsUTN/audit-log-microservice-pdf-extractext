"""Configuración del servicio.

Se lee una vez, al arrancar, del entorno. `SERVICE_API_TOKEN` no tiene default a
propósito: sin él el servicio se niega a arrancar (SPEC §3.6), lo que convierte un
orquestador mal configurado en un fallo de arranque ruidoso en vez de una
auditoría que deja de crecer en silencio (SPEC §2.5 H5).

El token es un `SecretStr`, así que no puede filtrarse por un `repr` ni por un
`logger.info("%s", settings)` perdido por el camino. Esa garantía es la razón
del tipo, no decoración.
"""

from collections.abc import Mapping

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de ejecución del servicio de auditoría."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Audit Log Microservice"
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
        """Tratar como ausente un token formado sólo por espacios.

        El mensaje nombra la variable y nunca su valor: este error se imprime
        entero cuando el servicio se niega a arrancar.
        """
        if not token.get_secret_value().strip():
            raise ValueError(
                "service_api_token must not be empty: generate one with "
                "'python -c \"import secrets; print(secrets.token_urlsafe(32))\"'"
            )
        return token


def get_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Construir la configuración.

    Se invoca desde la fábrica de la app, nunca a nivel de módulo: importar este
    módulo no debe exigir un entorno.

    Args:
        environ: Entorno explícito del que leer, para los tests. Si se omite se
            leen el entorno del proceso y el fichero `.env`.

    Returns:
        La configuración validada.

    Raises:
        ValidationError: Si falta el token o está en blanco, o si un límite no es
            un número positivo.
    """
    if environ is None:
        return Settings()
    return Settings(**{key.lower(): value for key, value in environ.items()})
