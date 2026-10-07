"""T11: la doble barrera bajo concurrencia real.

SPEC §5.3 defiende la idempotencia con dos barreras: la Barrera 1 (`find_replay`)
corta el reintento normal, y la Barrera 2 —el índice único decidido por MongoDB
ante la carrera— convierte el `DuplicateKeyError` de los perdedores en el mismo
`200` de replay. Lo que T11 prueba es que la segunda barrera no es decorativa:
si se desactiva su traducción a `ReplayDetected`, el test de abajo se rompe.

Dos escenarios, el mismo hecho:

- El vertical HTTP: N `POST /audit/logs` idénticos lanzados a la vez contra la app
  real. El observable no depende de qué barrera atrapa a cada perdedor: exactamente
  un `201`, N-1 `200` de replay, y un solo documento.
- La carrera a nivel de servicio con `asyncio.gather`: N `service.create` sobre un
  mismo índice único real. Los N pasan la Barrera 1 casi a la vez (nadie ha
  insertado todavía) y el índice decide el único ganador; los demás se traducen por
  la Barrera 2. Este segundo escenario es el que **exige** la traducción: sin ella,
  un perdedor de la carrera lanzaría el `DuplicateKeyError` crudo y el test
  explotaría.

Por qué el gate es la Capa 3 real y no un doble: con un repositorio fake las N
peticiones se serializarían unas tras otras, la Barrera 1 cortaría a todas menos
a la primera y la Barrera 2 nunca se ejercitaría —una defensa decorativa. Aquí la
carrera la resuelve MongoDB de verdad, repetida `LOOPS` veces sin `sleep` ni
polling, y el conteo de documentos se lee de la colección real.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

from fastapi.testclient import TestClient

from app.domain.models import CreateAuditLogRequest
from app.main import create_app
from app.repositories.mongo_audit_log_repository import MongoAuditLogRepository
from app.repositories.mongodb import ensure_indexes
from app.services.audit_log_service import AuditLogService
from tests.integration.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
WORKERS = 10
LOOPS = 20
CHECKSUM = "9f86d081884c7d659a2feaa0c55ad015"


def _event_payload(iteration: int) -> dict[str, object]:
    """Un evento distinto por iteración, idéntico dentro de ella."""
    return {
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
        "details": {"iteration": iteration},
        "performed_at": f"2026-10-05T12:34:{iteration:02d}.000Z",
    }


def _request(iteration: int) -> CreateAuditLogRequest:
    """El mismo evento como petición de dominio, para la carrera a nivel servicio."""
    payload = _event_payload(iteration)
    action = str(payload["action"])
    entity_type = str(payload["entity_type"])
    checksum = str(payload["checksum"])
    performed_at = datetime.fromisoformat(str(payload["performed_at"])).replace(
        tzinfo=UTC
    )
    return CreateAuditLogRequest(
        action=action,
        entity_type=entity_type,
        checksum=checksum,
        performed_at=performed_at,
        details={"iteration": iteration},
    )


async def test_ten_concurrent_posts_leave_exactly_one_document_and_one_201(
    deployed: None, clean_collection: object
) -> None:
    """N `POST` idénticos simultáneos: un `201`, N-1 `200` de replay, un doc.

    El `Barrier` del cliente sólo sincroniza la salida de los N hilos; dentro de la
    app la carrera la resuelve el índice único real. La identidad cambia por
    iteración para que cada bucle vuelva a empezar de cero.
    """
    with TestClient(create_app()) as client:
        for iteration in range(LOOPS):
            payload = _event_payload(iteration)
            start = Barrier(WORKERS)

            def post_one(
                _: int, event: dict[str, object] = payload, gate: Barrier = start
            ) -> tuple[int, str, bool]:
                gate.wait()
                response = client.post("/audit/logs", json=event, headers=AUTH)
                body = response.json()
                replay = response.headers.get("X-Idempotent-Replay")
                return (
                    response.status_code,
                    replay or "",
                    bool(body["idempotent_replay"]),
                )

            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                outcomes = list(pool.map(post_one, range(WORKERS)))

            codes = [outcome[0] for outcome in outcomes]
            assert sorted(codes) == [200] * (WORKERS - 1) + [201]
            for code, header, body_replay in outcomes:
                if code == 201:
                    assert header == ""
                    assert body_replay is False
                else:
                    assert header == "true"
                    assert body_replay is True

            assert (
                await clean_collection.count_documents({"checksum": CHECKSUM})
                == iteration + 1
            )


async def test_the_unique_index_decides_one_winner_under_full_concurrency(
    deployed: None, clean_collection: object
) -> None:
    """La traducción de `DuplicateKeyError` no es decorativa: la carrera la exige.

    N `service.create` concurrentes sobre un índice único real: todos pasan la
    Barrera 1 casi a la vez (la colección está vacía), el índice decide el único
    ganador y el resto cae en la Barrera 2. Quitar la traducción de la Capa 3
    hace explotar este test con el `DuplicateKeyError` crudo.
    """
    await ensure_indexes(clean_collection, retention_days=0)
    repository = MongoAuditLogRepository(clean_collection)
    service = AuditLogService(repository)

    for iteration in range(LOOPS):
        request = _request(iteration)
        results = await asyncio.gather(
            *(service.create(request) for _ in range(WORKERS))
        )

        replays = [result.replay for result in results]
        assert replays.count(False) == 1
        assert replays.count(True) == WORKERS - 1
        assert await clean_collection.count_documents({}) == iteration + 1
