"""Minimal Consul agent API client for service lifecycle."""

import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.consul import ConsulConfigurationError


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
    if not service_id.strip():
        raise ConsulConfigurationError("CONSUL_SERVICE_ID must not be empty")
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
    if not address.strip() or not token.strip():
        raise ConsulConfigurationError(
            "CONSUL_HTTP_ADDR and CONSUL_HTTP_TOKEN are required"
        )
    body = None if payload is None else json.dumps(payload).encode()
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
                    f"Consul service request returned HTTP {response.status}"
                )
    except (HTTPError, URLError, TimeoutError) as error:
        raise ConsulConfigurationError(
            "unable to update Consul service registry"
        ) from error
