"""Resolución de configuración y registro de ciclo de vida en Consul.

La configuración se lee del entorno o de Consul, y el servicio se registra en
Consul sólo cuando `CONSUL_ENABLED=true`.
"""

import os
import socket
from typing import Any

from app.config import Settings, get_settings, get_settings_from_values
from app.consul import load_prefix


def settings_from_environment_or_consul() -> Settings:
    """Resolver la configuración desde el entorno o desde Consul."""
    if os.getenv("CONSUL_ENABLED", "").lower() != "true":
        return get_settings()
    values = load_prefix(
        os.getenv("CONSUL_HTTP_ADDR", ""),
        os.getenv("CONSUL_HTTP_TOKEN", ""),
        os.getenv("CONSUL_KV_PREFIX", ""),
        ca_file=os.getenv("CONSUL_HTTP_CA_FILE"),
    )
    return get_settings_from_values(values)


def consul_registration() -> dict[str, Any] | None:
    """Payload para registrar el servicio en Consul, o `None` si está deshabilitado."""
    if os.getenv("CONSUL_ENABLED", "").lower() != "true":
        return None
    address = os.getenv("CONSUL_SERVICE_ADDRESS") or socket.gethostname()
    port = int(os.getenv("CONSUL_SERVICE_PORT", os.getenv("PORT", "8000")))
    service_name = os.getenv("CONSUL_SERVICE_NAME", "auditlog")
    service_id = os.getenv("CONSUL_SERVICE_ID") or f"{service_name}-{address}"
    tags_env = os.getenv("CONSUL_SERVICE_TAGS", "")
    # Separador de tags: ';'. Las comas son parte del valor (p. ej. la lista de
    # middlewares de Traefik: "security-headers@file,audit-cb@file"), por lo
    # que NO deben usarse como separador.
    tags: list[str] = []
    for part in tags_env.split(";"):
        tag = part.strip()
        if tag:
            tags.append(tag)
    return {
        "address": os.getenv("CONSUL_HTTP_ADDR", ""),
        "token": os.getenv("CONSUL_HTTP_TOKEN", ""),
        "ca_file": os.getenv("CONSUL_HTTP_CA_FILE"),
        "service_id": service_id,
        "service_name": service_name,
        "service_address": address,
        "service_port": port,
        "check_url": os.getenv(
            "CONSUL_SERVICE_CHECK_URL",
            f"http://{address}:{port}/readyz",
        ),
        "tags": tags,
    }
