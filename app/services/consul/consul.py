"""Lee la configuración guardada en Consul."""

import base64
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ConsulConfigurationError(RuntimeError):
    """Consul no pudo proporcionar un prefijo de configuración válido."""


def load_prefix(
    address: str,
    token: str,
    prefix: str,
    *,
    timeout: float = 5.0,
    ca_file: str | None = None,
) -> dict[str, str]:
    """Lee los valores de configuración guardados en Consul.

    Args:
        address: Dirección del servidor de Consul.
        token: Token de acceso.
        prefix: Prefijo de las claves en Consul.
        timeout: Tiempo máximo de espera en segundos.
        ca_file: Ruta del certificado de autoridad.

    Returns:
        Un diccionario con las claves y sus valores.

    Raises:
        ConsulConfigurationError: Si la dirección, el token o el prefijo no son
            válidos, o si Consul responde con un error.
    """
    if not address.strip() or not token.strip() or not prefix.strip():
        raise ConsulConfigurationError(
            "CONSUL_HTTP_ADDR, CONSUL_HTTP_TOKEN y CONSUL_KV_PREFIX son obligatorios"
        )

    url = f"{address.rstrip('/')}/v1/kv/{prefix.lstrip('/')}?recurse=true"
    request = Request(url, headers={"X-Consul-Token": token})
    try:
        context = ssl.create_default_context(cafile=ca_file) if ca_file else None
        with urlopen(request, timeout=timeout, context=context) as response:
            entries = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise ConsulConfigurationError(
            "no se pudo leer el prefijo KV de Consul"
        ) from error

    values: dict[str, str] = {}
    normalized_prefix = prefix.rstrip("/") + "/"
    for entry in entries:
        key = entry["Key"]
        if not key.startswith(normalized_prefix) or key == normalized_prefix:
            raise ConsulConfigurationError(
                "Consul devolvió una clave fuera del prefijo configurado"
            )
        try:
            values[key.removeprefix(normalized_prefix)] = base64.b64decode(
                entry["Value"], validate=True
            ).decode()
        except (KeyError, ValueError, UnicodeDecodeError) as error:
            raise ConsulConfigurationError(
                "valor inválido en la respuesta KV de Consul"
            ) from error
    return values
