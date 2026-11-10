"""Registra y quita el servicio en Consul."""

import json
import os
import socket
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.consul.consul import ConsulConfigurationError


def consul_registration() -> dict[str, Any] | None:
    """Prepara los datos para registrar el servicio en Consul."""
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


def register_service(
    address: str,
    token: str,
    *,
    service_id: str,
    service_name: str,
    service_address: str,
    service_port: int,
    check_url: str,
    tags: list[str] | None = None,
    timeout: float = 5.0,
    ca_file: str | None = None,
) -> None:
    """Registra el servicio y su chequeo de salud en Consul.

    Args:
        address: Dirección del servidor de Consul.
        token: Token de acceso.
        service_id: Identificador del servicio en Consul.
        service_name: Nombre del servicio.
        service_address: Dirección del servicio.
        service_port: Puerto del servicio.
        check_url: URL del chequeo de salud.
        tags: Etiquetas del servicio.
        timeout: Tiempo máximo de espera en segundos.
        ca_file: Ruta del certificado de autoridad.

    Returns:
        No retorna valor.

    Raises:
        ConsulConfigurationError: Si el registro no se puede completar.
    """
    _request(
        address,
        token,
        "/v1/agent/service/register",
        {
            "ID": service_id,
            "Name": service_name,
            "Address": service_address,
            "Port": service_port,
            "Tags": tags or [],
            "Check": {
                "HTTP": check_url,
                "Interval": "10s",
                "Timeout": "3s",
                "DeregisterCriticalServiceAfter": "1m",
            },
        },
        timeout,
        ca_file,
    )


def deregister_service(
    address: str,
    token: str,
    service_id: str,
    *,
    timeout: float = 5.0,
    ca_file: str | None = None,
) -> None:
    """Elimina el registro del servicio en Consul.

    Args:
        address: Dirección del servidor de Consul.
        token: Token de acceso.
        service_id: Identificador del servicio en Consul.
        timeout: Tiempo máximo de espera en segundos.
        ca_file: Ruta del certificado de autoridad.

    Returns:
        No retorna valor.

    Raises:
        ConsulConfigurationError: Si el servicio no se puede quitar.
    """
    if not service_id.strip():
        raise ConsulConfigurationError("CONSUL_SERVICE_ID no debe estar vacío")
    _request(
        address,
        token,
        f"/v1/agent/service/deregister/{service_id}",
        None,
        timeout,
        ca_file,
    )


def _request(
    address: str,
    token: str,
    path: str,
    payload: dict[str, object] | None,
    timeout: float,
    ca_file: str | None,
) -> None:
    """Envía una petición al agente de Consul.

    Args:
        address: Dirección del servidor de Consul.
        token: Token de acceso.
        path: Ruta de la petición.
        payload: Datos que se van a enviar.
        timeout: Tiempo máximo de espera en segundos.
        ca_file: Ruta del certificado de autoridad.

    Returns:
        No retorna valor.

    Raises:
        ConsulConfigurationError: Si Consul responde con un error o no está
            disponible.
    """
    if not address.strip() or not token.strip():
        raise ConsulConfigurationError(
            "CONSUL_HTTP_ADDR y CONSUL_HTTP_TOKEN son obligatorios"
        )
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    request = Request(
        f"{address.rstrip('/')}{path}",
        data=body,
        method="PUT",
        headers={"X-Consul-Token": token, "Content-Type": "application/json"},
    )
    try:
        context = ssl.create_default_context(cafile=ca_file) if ca_file else None
        with urlopen(request, timeout=timeout, context=context) as response:
            if response.status // 100 != 2:
                raise ConsulConfigurationError(
                    f"La solicitud del servicio de Consul devolvió HTTP {response.status}"
                )
    except (HTTPError, URLError, TimeoutError) as error:
        raise ConsulConfigurationError(
            "no se pudo actualizar el registro del servicio de Consul"
        ) from error
