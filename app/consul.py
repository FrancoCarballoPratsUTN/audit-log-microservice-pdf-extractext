"""Minimal Consul KV client used during service startup."""

import base64
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ConsulConfigurationError(RuntimeError):
    """Consul could not provide a valid configuration prefix."""


def load_prefix(
    address: str,
    token: str,
    prefix: str,
    *,
    timeout: float = 5.0,
    ca_file: str | None = None,
) -> dict[str, str]:
    if not address.strip() or not token.strip() or not prefix.strip():
        raise ConsulConfigurationError(
            "CONSUL_HTTP_ADDR, CONSUL_HTTP_TOKEN and CONSUL_KV_PREFIX are required"
        )

    url = f"{address.rstrip('/')}/v1/kv/{prefix.lstrip('/')}?recurse=true"
    request = Request(url, headers={"X-Consul-Token": token})
    try:
        context = ssl.create_default_context(cafile=ca_file) if ca_file else None
        with urlopen(request, timeout=timeout, context=context) as response:
            entries = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise ConsulConfigurationError("unable to read Consul KV prefix") from error

    values: dict[str, str] = {}
    normalized_prefix = prefix.rstrip("/") + "/"
    for entry in entries:
        key = entry["Key"]
        if not key.startswith(normalized_prefix) or key == normalized_prefix:
            raise ConsulConfigurationError(
                "Consul returned a key outside the configured prefix"
            )
        try:
            values[key.removeprefix(normalized_prefix)] = base64.b64decode(
                entry["Value"], validate=True
            ).decode()
        except (KeyError, ValueError, UnicodeDecodeError) as error:
            raise ConsulConfigurationError(
                "invalid value in Consul KV response"
            ) from error
    return values
