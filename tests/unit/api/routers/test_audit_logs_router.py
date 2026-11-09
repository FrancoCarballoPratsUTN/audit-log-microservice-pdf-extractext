"""Pruebas del router de auditorías sin base de datos."""

import json
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

RAW_EVENT_PREFIX = (
    '{"action":"pdf.extract","entity_type":"document",'
    '"checksum":"9f86d081884c7d659a2feaa0c55ad015",'
    '"performed_at":"2026-10-05T12:34:56.789Z","details":'
)


def _app(
    service: SpyingService,
    *,
    max_details_bytes: int = 65536,
    default_limit: int = 10,
) -> FastAPI:
    """Crea una aplicación de prueba con el servicio indicado.

    Args:
        service: Servicio de auditoría.
        max_details_bytes: Tamaño máximo de los detalles.
        default_limit: Cantidad de resultados por defecto.

    Returns:
        La aplicación de prueba.
    """
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
    """Crea un registro de auditoría de prueba.

    Args:
        checksum: Valor que identifica el contenido.

    Returns:
        El registro de prueba.
    """
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
        """Guarda el resultado y los elementos que devolverá.

        Args:
            result: Resultado del servicio.
            items: Registros iniciales del repositorio.

        Returns:
            No retorna valor.
        """
        self.result = result
        self.list_items = list(items or [])
        self.created: list[CreateAuditLogRequest] = []
        self.list_calls: list[tuple[int, int]] = []
        self.checksum_calls: list[str] = []

    async def create(self, request: CreateAuditLogRequest) -> CreateResult:
        """Devuelve el resultado preparado y guarda la petición.

        Args:
            request: Petición HTTP recibida.

        Returns:
            El resultado creado.
        """
        self.created.append(request)
        if self.result is None:
            raise AssertionError(
                "SpyingService.create recibió una llamada sin resultado"
            )
        return self.result

    async def list_page(self, *, skip: int, limit: int) -> list[AuditLog]:
        """Devuelve los elementos preparados y guarda la paginación.

        Args:
            skip: Cantidad de resultados que se van a omitir.
            limit: Cantidad máxima de resultados.

        Returns:
            La lista de elementos.
        """
        self.list_calls.append((skip, limit))
        return self.list_items

    async def list_by_checksum(self, checksum: str) -> list[AuditLog]:
        """Devuelve los elementos del checksum indicado.

        Args:
            checksum: Valor que identifica el contenido.

        Returns:
            La lista de elementos.
        """
        self.checksum_calls.append(checksum)
        return self.list_items


def _post(service: SpyingService, *payloads: dict, limit: int = 65536):
    """Envía una petición POST de prueba.

    Args:
        service: Servicio de auditoría.
        limit: Cantidad máxima de resultados.
        *payloads: Argumentos adicionales.

    Returns:
        La respuesta de la API.
    """
    client = TestClient(_app(service, max_details_bytes=limit))
    responses = [client.post("/audit/logs", json=payload) for payload in payloads]
    return responses[0] if len(responses) == 1 else responses


def _get(service: SpyingService, *, default_limit: int = 10, **params: object):
    """Envía una petición GET de prueba al listado.

    Args:
        service: Servicio de auditoría.
        default_limit: Cantidad de resultados por defecto.
        **params: Argumentos adicionales.

    Returns:
        La respuesta de la API.
    """
    client = TestClient(_app(service, default_limit=default_limit))
    return client.get("/audit/logs", params=params)


def _get_by_checksum(service: SpyingService, checksum: str):
    """Envía una petición GET de prueba por checksum.

    Args:
        service: Servicio de auditoría.
        checksum: Valor que identifica el contenido.

    Returns:
        La respuesta de la API.
    """
    client = TestClient(_app(service))
    return client.get(f"/audit/logs/checksum/{checksum}")


def test_a_created_event_returns_201_with_location_and_the_seven_fields() -> None:
    """Comprueba que un evento creado devuelve 201, Location y los siete campos."""
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
    """Comprueba que un duplicado devuelve 200 con ambas señales."""
    response = _post(SpyingService(CreateResult(_log(), replay=True)), VALID_EVENT)

    assert response.status_code == 200
    assert response.headers["X-Idempotent-Replay"] == "true"
    assert (
        response.headers["Location"]
        == "/audit/logs/checksum/9f86d081884c7d659a2feaa0c55ad015"
    )
    assert response.json()["idempotent_replay"] is True


def test_details_over_the_limit_returns_413_without_calling_the_service() -> None:
    """Comprueba que unos detalles demasiado grandes devuelven 413 sin llamar al
    servicio.
    """
    service = SpyingService(CreateResult(_log(), replay=False))
    payload = {**VALID_EVENT, "details": {"blob": "x" * 32}}

    response = _post(service, payload, limit=16)

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert service.created == []


def test_a_recursion_error_while_serializing_details_is_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un anidamiento que revienta el serializador no puede escapar como `500`.

    Args:
        monkeypatch: Utilidad de pytest para sustituir valores.

    Returns:
        No retorna valor.
    """
    service = SpyingService(CreateResult(_log(), replay=False))
    real_dumps = json.dumps

    def dumps(value, *args, **kwargs):
        """Simula un error de recursión al convertir los detalles.

        Args:
            value: Valor que se va a revisar.
            *args: Argumentos adicionales.
            **kwargs: Argumentos adicionales.

        Returns:
            El texto JSON.
        """
        if isinstance(value, dict) and value.get("trigger") == "recursion":
            raise RecursionError("maximum recursion depth exceeded")
        return real_dumps(value, *args, **kwargs)

    monkeypatch.setattr("app.api.validators.details.json.dumps", dumps)

    response = _post(service, {**VALID_EVENT, "details": {"trigger": "recursion"}})

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert service.created == []


@pytest.mark.parametrize(
    "details",
    [
        float("nan"),
        float("inf"),
        -float("inf"),
        2**63,
        {"bad\x00key": "value"},
    ],
    ids=[
        "nan",
        "infinity",
        "negative-infinity",
        "integer-out-of-bson-range",
        "nul-key",
    ],
)
def test_details_that_cannot_be_stored_as_bson_return_400_before_service(
    details: object,
) -> None:
    """Comprueba que unos detalles no válidos para BSON devuelven 400 antes del
    servicio.

    Args:
        details: Datos adicionales del evento.

    Returns:
        No retorna valor.
    """
    service = SpyingService(CreateResult(_log(), replay=False))

    client = TestClient(_app(service))
    body = RAW_EVENT_PREFIX + json.dumps(details, allow_nan=True) + "}"
    response = client.post(
        "/audit/logs",
        content=body,
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert service.created == []


def test_excessively_nested_details_return_400_before_service() -> None:
    """Comprueba que unos detalles demasiado anidados devuelven 400 antes del servicio.
    """
    service = SpyingService(CreateResult(_log(), replay=False))
    details: object = "leaf"
    for _ in range(150):
        details = [details]

    client = TestClient(_app(service))
    body = RAW_EVENT_PREFIX + json.dumps(details) + "}"
    response = client.post(
        "/audit/logs",
        content=body,
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert service.created == []


def test_rejected_details_do_not_poison_a_later_list_response() -> None:
    """Comprueba que unos detalles rechazados no afectan a un listado posterior."""
    service = SpyingService(CreateResult(_log(), replay=False))
    client = TestClient(_app(service))
    invalid_body = RAW_EVENT_PREFIX + '{"bad\\u0000key":"value"}}'
    headers = {
        "Authorization": "Bearer test",
        "Content-Type": "application/json",
    }

    rejected = client.post("/audit/logs", content=invalid_body, headers=headers)
    listed = client.get("/audit/logs", headers=headers)

    assert rejected.status_code == 400
    assert listed.status_code == 200
    assert listed.json() == []
    assert service.created == []


def test_details_size_limit_counts_utf8_bytes() -> None:
    """Comprueba que el límite cuenta los bytes UTF-8."""
    details = {"text": "á" * 20}
    encoded = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
    service = SpyingService(CreateResult(_log(), replay=False))

    response = _post(
        service, {**VALID_EVENT, "details": details}, limit=len(encoded.encode())
    )

    assert response.status_code == 201
    assert service.created[0].details == details


def test_details_over_utf8_byte_limit_return_413_before_service() -> None:
    """Comprueba que unos detalles por encima del límite devuelven 413 antes del
    servicio.
    """
    details = {"text": "á" * 20}
    encoded = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
    service = SpyingService(CreateResult(_log(), replay=False))

    response = _post(
        service,
        {**VALID_EVENT, "details": details},
        limit=len(encoded.encode()) - 1,
    )

    assert response.status_code == 413
    assert service.created == []


def test_absent_details_reach_the_service_as_an_empty_object() -> None:
    """Comprueba que unos detalles ausentes llegan al servicio como objeto vacío."""
    service = SpyingService(CreateResult(_log(), replay=False))
    payload = {k: v for k, v in VALID_EVENT.items() if k != "details"}

    response = _post(service, payload)

    assert response.status_code == 201
    assert service.created[0].details == {}


def test_nested_details_pass_verbatim_to_the_service() -> None:
    """Comprueba que los detalles anidados llegan sin cambios al servicio."""
    service = SpyingService(CreateResult(_log(), replay=False))
    details = {"nested": {"deep": [1, 2, {"x": None}]}}
    payload = {**VALID_EVENT, "details": details}

    response = _post(service, payload)

    assert response.status_code == 201
    assert service.created[0].details == details


def test_the_location_escapes_every_character_of_the_checksum() -> None:
    """Comprueba que la ubicación escapa todos los caracteres del checksum."""
    checksum = 'Mi-/checksum?&="raro" #mañana'
    service = SpyingService(CreateResult(_log(checksum=checksum), replay=False))

    response = _post(service, {**VALID_EVENT, "checksum": checksum})

    assert response.status_code == 201
    assert response.headers["Location"] == "/audit/logs/checksum/" + quote(
        checksum, safe=""
    )


def test_an_invalid_body_is_400_before_the_service() -> None:
    """Comprueba que un cuerpo inválido devuelve 400 antes del servicio."""
    service = SpyingService(CreateResult(_log(), replay=False))
    payload = {**VALID_EVENT, "performed_at": "2026-10-05T12:34:56"}

    response = _post(service, payload)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert service.created == []


def test_list_returns_a_top_level_array_with_the_seven_decodable_fields() -> None:
    """El `GET` responde un **array de primer nivel** y cada elemento lleva exactamente
    los 7 campos de `models.AuditLog` — sin e...
    """
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
    """Comprueba que el listado reenvía skip y limit al servicio."""
    service = SpyingService(items=[])

    response = _get(service, skip=5, limit=20)

    assert response.status_code == 200
    assert service.list_calls == [(5, 20)]


def test_list_applies_the_configured_default_limit() -> None:
    """`limit` ausente ⇒ `DEFAULT_LIMIT` del despliegue (coincide con el del
    orquestador, SPEC `DEFAULT_LIMIT`), aplicado en la Capa 1.
    """
    service = SpyingService(items=[])

    response = _get(service, default_limit=7)

    assert response.status_code == 200
    assert service.list_calls == [(0, 7)]


@pytest.mark.parametrize(
    "params",
    [{"skip": -1}, {"skip": 10001}, {"limit": 0}, {"limit": 101}],
)
def test_list_rejects_out_of_range_pagination_with_400(params: dict[str, int]) -> None:
    """El rango se rechaza, **nunca** se recorta; `400 VALIDATION_ERROR` como el body
    inválido, y el servicio ni se entera.

    Args:
        params: Parámetros de la consulta.

    Returns:
        No retorna valor.
    """
    service = SpyingService(items=[])

    response = _get(service, **params)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert service.list_calls == []


def test_list_with_no_results_returns_an_empty_array() -> None:
    """Comprueba que un listado vacío devuelve un arreglo vacío."""
    response = _get(SpyingService(items=[]))

    assert response.status_code == 200
    assert response.json() == []


def test_list_by_checksum_returns_a_top_level_array_with_the_seven_fields() -> None:
    """El listado por checksum repite la forma de la lectura global —array de primer
    nivel, 7 campos— sin el `idempotent_replay` de escritura.
    """
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
    """Comprueba que el listado por checksum reenvía el valor de la ruta."""
    service = SpyingService(items=[])

    response = _get_by_checksum(service, "abc123")

    assert response.status_code == 200
    assert service.checksum_calls == ["abc123"]


def test_list_by_checksum_with_no_results_returns_an_empty_array() -> None:
    """`client_test.go:170`: sin resultados es `200 []`, nunca `404`."""
    response = _get_by_checksum(SpyingService(items=[]), "checksum-inexistente")

    assert response.status_code == 200
    assert response.json() == []
