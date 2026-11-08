import base64
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.error import URLError

import pytest

from app.consul import ConsulConfigurationError, load_prefix
from app.consul_agent import deregister_service, register_service


class FakeResponse:
    """Respuesta mínima para los caminos que no usan un servidor real."""

    def __init__(self, body: bytes = b"", status: int = 200) -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def read(self, *_args: object) -> bytes:
        return self._body


def test_load_prefix_decodes_values_and_sends_token():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.headers["X-Consul-Token"] == "service-token"
            body = json.dumps(
                [
                    {
                        "Key": "pdf-extractext/dev/auditlog/MAX_LIMIT",
                        "Value": base64.b64encode(b"100").decode(),
                    }
                ]
            ).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.handle_request, daemon=True).start()
    try:
        values = load_prefix(
            f"http://127.0.0.1:{server.server_port}",
            "service-token",
            "pdf-extractext/dev/auditlog/",
        )
    finally:
        server.server_close()

    assert values == {"MAX_LIMIT": "100"}


def test_service_registration_uses_agent_api_and_token():
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            paths.append(self.path)
            assert self.headers["X-Consul-Token"] == "service-token"
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        address = f"http://127.0.0.1:{server.server_port}"
        register_service(
            address,
            "service-token",
            service_id="auditlog-1",
            service_name="auditlog",
            service_address="auditlog-1",
            service_port=8000,
            check_url="http://auditlog-1:8000/readyz",
        )
        deregister_service(address, "service-token", "auditlog-1")
    finally:
        server.shutdown()
        server.server_close()

    assert paths == [
        "/v1/agent/service/register",
        "/v1/agent/service/deregister/auditlog-1",
    ]


def test_load_prefix_requires_connection_settings() -> None:
    with pytest.raises(ConsulConfigurationError, match="required"):
        load_prefix("", "service-token", "prefix")


def test_load_prefix_wraps_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise URLError("down")

    monkeypatch.setattr("app.consul.urlopen", fail)

    with pytest.raises(ConsulConfigurationError, match="unable to read"):
        load_prefix("http://consul:8500", "service-token", "prefix")


def test_load_prefix_rejects_keys_outside_the_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps([{"Key": "other/MAX_LIMIT", "Value": "MTAw"}]).encode()
    monkeypatch.setattr(
        "app.consul.urlopen", lambda *_args, **_kwargs: FakeResponse(body)
    )

    with pytest.raises(ConsulConfigurationError, match="outside"):
        load_prefix("http://consul:8500", "service-token", "prefix")


def test_load_prefix_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps([{"Key": "prefix/MAX_LIMIT"}]).encode()
    monkeypatch.setattr(
        "app.consul.urlopen", lambda *_args, **_kwargs: FakeResponse(body)
    )

    with pytest.raises(ConsulConfigurationError, match="invalid value"):
        load_prefix("http://consul:8500", "service-token", "prefix")


def test_deregister_service_rejects_a_blank_id() -> None:
    with pytest.raises(ConsulConfigurationError, match="CONSUL_SERVICE_ID"):
        deregister_service("http://consul:8500", "service-token", "   ")


def test_consul_agent_requires_an_address() -> None:
    with pytest.raises(ConsulConfigurationError, match="CONSUL_HTTP_ADDR"):
        deregister_service("", "service-token", "auditlog-1")


def test_consul_agent_rejects_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeResponse(status=503)
    monkeypatch.setattr("app.consul_agent.urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(ConsulConfigurationError, match="HTTP 503"):
        deregister_service("http://consul:8500", "service-token", "auditlog-1")


def test_consul_agent_wraps_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise URLError("down")

    monkeypatch.setattr("app.consul_agent.urlopen", fail)

    with pytest.raises(ConsulConfigurationError, match="unable to update"):
        deregister_service("http://consul:8500", "service-token", "auditlog-1")
