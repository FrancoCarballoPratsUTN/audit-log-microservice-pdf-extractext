"""Readiness real: ping en cada sondeo e índices una sola vez.

Un `ping` correcto no basta para atender tráfico: el servicio también necesita
los índices de SPEC §6.3, que pueden faltar aunque Mongo responda. La sonda
separa ambos fallos y reintenta la creación de índices tras una caída, sin
volver a crearlos cuando ya están listos.

Los dobles viven en `tests/fakes/fake_mongo.py`; aquí se añaden los que tienen
comportamiento temporal o concurrente, porque son específicos de esta sonda.
"""

import asyncio

import pytest
from pymongo.errors import OperationFailure

from app.errors import AuditStorageError
from app.repositories.readiness import ReadinessProbe
from tests.fakes.fake_mongo import FailingClient, WorkingClient, WorkingCollection


class FlakyCollection:
    """Falla la primera creación de índices y acepta la siguiente."""

    def __init__(self) -> None:
        self.create_calls = 0
        self.fail = True

    async def create_indexes(self, models: list[object]) -> list[str]:
        self.create_calls += 1
        if self.fail:
            self.fail = False
            raise OperationFailure("temporary index failure")
        return []


class BlockingCollection:
    """Mantiene la primera creación de índices abierta hasta que el test la libera."""

    def __init__(self) -> None:
        self.create_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def create_indexes(self, models: list[object]) -> list[str]:
        self.create_calls += 1
        self.started.set()
        await self.release.wait()
        return []


async def test_readiness_pings_every_time_and_creates_indexes_once() -> None:
    """El ping es por sondeo; los índices son estado del proceso.

    Si los índices se recrearan en cada `/readyz`, un sondeo periódico haría
    trabajo de administración de Mongo cada pocos segundos.
    """
    client = WorkingClient()
    collection = WorkingCollection()
    probe = ReadinessProbe(client, collection, retention_days=30)

    assert probe.indexes_ready is False

    await probe()
    await probe()

    assert probe.indexes_ready is True
    assert client.admin.pings == ["ping", "ping"]
    assert collection.create_calls == 1
    assert len(collection.models) == 4


async def test_a_failed_ping_does_not_try_to_create_indexes() -> None:
    """Mongo inalcanzable y índices ausentes son fallos distintos.

    Si el ping falla, no tiene sentido intentar crear índices: el error de
    conexión es el que debe llegar al `/readyz`.
    """
    collection = WorkingCollection()
    probe = ReadinessProbe(FailingClient(), collection, retention_days=0)

    with pytest.raises(AuditStorageError):
        await probe()

    assert probe.indexes_ready is False
    assert collection.create_calls == 0


async def test_indexes_are_retried_after_the_first_attempt_fails() -> None:
    """Un fallo transitorio de creación no puede dejar el servicio en `503`.

    Cuando Mongo vuelve, la siguiente sonda debe volver a intentar los índices.
    """
    collection = FlakyCollection()
    probe = ReadinessProbe(WorkingClient(), collection, retention_days=0)

    with pytest.raises(AuditStorageError):
        await probe()

    assert probe.indexes_ready is False

    await probe()

    assert probe.indexes_ready is True
    assert collection.create_calls == 2


async def test_concurrent_readiness_checks_create_indexes_once() -> None:
    """El lock evita que varios `/readyz` creen los índices a la vez.

    Sin serialización, dos sondeos concurrentes pueden lanzar `create_indexes`
    en paralelo y uno de ellos falla con un conflicto de índice.
    """
    collection = BlockingCollection()
    probe = ReadinessProbe(WorkingClient(), collection, retention_days=0)

    tasks = [asyncio.create_task(probe.ensure_indexes()) for _ in range(3)]
    await asyncio.wait_for(collection.started.wait(), timeout=1)
    await asyncio.sleep(0)
    collection.release.set()
    await asyncio.gather(*tasks)

    assert collection.create_calls == 1
    assert probe.indexes_ready is True
