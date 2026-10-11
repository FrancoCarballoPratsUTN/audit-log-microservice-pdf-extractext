"""El router `POST /audit/logs` aislado del storage.

Se construye una app mínima con el router, sin lifespan ni Mongo, y se enchufa
un servicio de juguete en `app.state` — el mismo sitio donde el composition root
dejaría el de verdad, así que la dependencia por defecto de
`app/api/dependencies.py` se ejecuta tal cual. Lo que se fija aquí es la
traducción de Capa 1 que el test de integración no puede aislar: estado, `Location`,
cabeceras de replay y el límite de `details` **antes** de llamar a la Capa 2.

La persistencia real y "el documento existe en Mongo" son de
`tests/integration/api/test_create_audit_log.py`.
"""

from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.exception_handlers import register_exception_handlers
from app.api.routers.audit_logs import router as audit_logs_router
from app.config import get_settings
from app.domain.models import AuditLog, CreateAuditLogRequest
from app.services.audit_log_service import CreateResult

PERFORMED_AT = datetime(2026, 10, 5, 12, 34, 56, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 10, 5, 12, 35, 1, tzinfo=UTC)

VALID_EVENT = {
    "action": "pdf.extract",
    "entity_type": "document",
    "checksum": "9f86d081884c7d659a2feaa0c55ad015",
    "details": {"page_count": 12},
    "performed_at": "2026-10-05T12:34:56.789Z",
}


def _app(
    service: SpyingService,
    *,
    max_details_bytes: int = 65536,
    default_limit: int = 10,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(audit_logs_router)
    app.state.settings = get_settings(
        environ={
            "SERVICE_API_TOKEN": "test",
            "MAX_DETAILS_BYTES": str(max_details_bytes),
            "DEFAULT_LIMIT": str(default_limit),
        }
    )
    app.state.audit_log_service = service
    return app


def _log(checksum: str = "9f86d081884c7d659a2feaa0c55ad015") -> AuditLog:
    return AuditLog(
        id="6f1c9a2b3d4e5f60718293a4",
        action="pdf.extract",
        entity_type="document",
        checksum=checksum,
        performed_at=PERFORMED_AT,
        received_at=RECEIVED_AT,
        details={"page_count": 12},
    )


class SpyingService:
    """Doble del servicio: devuelve un resultado prefijado y registra las
    órdenes, para poder afirmar que una petición `413` nunca lo alcanza."""

    def __init__(
        self,
        result: CreateResult | None = None,
        *,
        items: list[AuditLog] | None = None,
    ) -> None:
        self.result = result
        self.list_items = list(items or [])
        self.created: list[CreateAuditLogRequest] = []
        self.list_calls: list[tuple[int, int]] = []
        self.checksum_calls: list[str] = []

    async def create(self, request: CreateAuditLogRequest) -> CreateResult:
        self.created.append(request)
        if self.result is None:
            raise AssertionError(
                "SpyingService.create recibió una llamada sin resultado"
            )
        return self.result

    async def list_page(self, *, skip: int, limit: int) -> list[AuditLog]:
        self.list_calls.append((skip, limit))
        return self.list_items

    async def list_by_checksum(self, checksum: str) -> list[AuditLog]:
        self.checksum_calls.append(checksum)
        return self.list_items


def _post(service: SpyingService, *payloads: dict, limit: int = 65536):
    client = TestClient(_app(service, max_details_bytes=limit))
    responses = [client.post("/audit/logs", json=payload) for payload in payloads]
    return responses[0] if len(responses) == 1 else responses


def _get(service: SpyingService, *, default_limit: int = 10, **params: object):
    client = TestClient(_app(service, default_limit=default_limit))
    return client.get("/audit/logs", params=params)


def _get_by_checksum(service: SpyingService, checksum: str):
    client = TestClient(_app(service))
    return client.get(f"/audit/logs/checksum/{checksum}")


def test_a_created_event_returns_201_with_location_and_the_seven_fields() -> None:
    response = _post(SpyingService(CreateResult(_log(), replay=False)), VALID_EVENT)

    body = response.json()
    assert response.status_code == 201
    assert (
        response.headers["Location"]
        == "/audit/logs/checksum/9f86d081884c7d659a2feaa0c55ad015"
    )
    assert body["_id"] == "6f1c9a2b3d4e5f60718293a4"
    assert body["action"] == "pdf.extract"
    assert body["entity_type"] == "document"
    assert body["checksum"] == "9f86d081884c7d659a2feaa0c55ad015"
    assert body["details"] == {"page_count": 12}
    assert body["performed_at"] == "2026-10-05T12:34:56.000Z"
    assert body["received_at"] == "2026-10-05T12:35:01.000Z"
    assert body["idempotent_replay"] is False


def test_a_replay_returns_200_with_both_idempotent_signals() -> None:
    response = _post(SpyingService(CreateResult(_log(), replay=True)), VALID_EVENT)

    assert response.status_code == 200
    assert response.headers["X-Idempotent-Replay"] == "true"
    assert (
        response.headers["Location"]
        == "/audit/logs/checksum/9f86d081884c7d659a2feaa0c55ad015"
    )
    assert response.json()["idempotent_replay"] is True


def test_details_over_the_limit_returns_413_without_calling_the_service() -> None:
    service = SpyingService(CreateResult(_log(), replay=False))
    payload = {**VALID_EVENT, "details": {"blob": "x" * 32}}

    response = _post(service, payload, limit=16)

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert service.created == []


def test_absent_details_reach_the_service_as_an_empty_object() -> None:
    service = SpyingService(CreateResult(_log(), replay=False))
    payload = {k: v for k, v in VALID_EVENT.items() if k != "details"}

    response = _post(service, payload)

    assert response.status_code == 201
    assert service.created[0].details == {}


def test_nested_details_pass_verbatim_to_the_service() -> None:
    service = SpyingService(CreateResult(_log(), replay=False))
    details = {"nested": {"deep": [1, 2, {"x": None}]}}
    payload = {**VALID_EVENT, "details": details}

    response = _post(service, payload)

    assert response.status_code == 201
    assert service.created[0].details == details


def test_the_location_escapes_every_character_of_the_checksum() -> None:
    checksum = 'Mi-/checksum?&="raro" #mañana'
    service = SpyingService(CreateResult(_log(checksum=checksum), replay=False))

    response = _post(service, {**VALID_EVENT, "checksum": checksum})

    assert response.status_code == 201
    assert response.headers["Location"] == "/audit/logs/checksum/" + quote(
        checksum, safe=""
    )


def test_an_invalid_body_is_400_before_the_service() -> None:
    service = SpyingService(CreateResult(_log(), replay=False))
    payload = {**VALID_EVENT, "performed_at": "2026-10-05T12:34:56"}

    response = _post(service, payload)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert service.created == []


def test_list_returns_a_top_level_array_with_the_seven_decodable_fields() -> None:
    """SPEC §2.4 y AC del plan: el `GET` responde un **array de primer nivel** y
    cada elemento lleva exactamente los 7 campos de `models.AuditLog` — sin el
    `idempotent_replay` que sólo existe en la respuesta de escritura."""
    service = SpyingService(items=[_log()])

    response = _get(service)

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert set(body[0]) == {
        "_id",
        "action",
        "entity_type",
        "checksum",
        "details",
        "performed_at",
        "received_at",
    }
    assert len(body[0]["_id"]) == 24
    assert body[0]["performed_at"].endswith("Z")
    assert body[0]["received_at"].endswith("Z")


def test_list_forwards_skip_and_limit_to_the_service() -> None:
    service = SpyingService(items=[])

    response = _get(service, skip=5, limit=20)

    assert response.status_code == 200
    assert service.list_calls == [(5, 20)]


def test_list_applies_the_configured_default_limit() -> None:
    """`limit` ausente ⇒ `DEFAULT_LIMIT` del despliegue (coincide con el del
    orquestador, SPEC `DEFAULT_LIMIT`), aplicado en la Capa 1."""
    service = SpyingService(items=[])

    response = _get(service, default_limit=7)

    assert response.status_code == 200
    assert service.list_calls == [(0, 7)]


@pytest.mark.parametrize(
    "params",
    [{"skip": -1}, {"skip": 10001}, {"limit": 0}, {"limit": 101}],
)
def test_list_rejects_out_of_range_pagination_with_400(params: dict[str, int]) -> None:
    """SPEC §5.2: el rango se rechaza, **nunca** se recorta; `400 VALIDATION_ERROR`
    como el body inválido, y el servicio ni se entera."""
    service = SpyingService(items=[])

    response = _get(service, **params)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert service.list_calls == []


def test_list_with_no_results_returns_an_empty_array() -> None:
    response = _get(SpyingService(items=[]))

    assert response.status_code == 200
    assert response.json() == []


def test_list_by_checksum_returns_a_top_level_array_with_the_seven_fields() -> None:
    """SPEC §8.1: el listado por checksum repite la forma de la lectura global
    —array de primer nivel, 7 campos— sin el `idempotent_replay` de escritura."""
    service = SpyingService(items=[_log()])

    response = _get_by_checksum(service, "9f86d081884c7d659a2feaa0c55ad015")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert set(body[0]) == {
        "_id",
        "action",
        "entity_type",
        "checksum",
        "details",
        "performed_at",
        "received_at",
    }
    assert body[0]["_id"] == "6f1c9a2b3d4e5f60718293a4"
    assert body[0]["performed_at"].endswith("Z")


def test_list_by_checksum_forwards_the_path_value_to_the_service() -> None:
    service = SpyingService(items=[])

    response = _get_by_checksum(service, "abc123")

    assert response.status_code == 200
    assert service.checksum_calls == ["abc123"]


def test_list_by_checksum_with_no_results_returns_an_empty_array() -> None:
    """`client_test.go:170`: sin resultados es `200 []`, nunca `404`."""
    response = _get_by_checksum(SpyingService(items=[]), "checksum-inexistente")

    assert response.status_code == 200
    assert response.json() == []
