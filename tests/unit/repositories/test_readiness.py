"""Pruebas de la comprobación de disponibilidad."""

import asyncio

import pytest
from pymongo.errors import OperationFailure

from app.errors import AuditStorageError
from app.repositories.readiness import ReadinessProbe
from tests.fakes.fake_mongo import FailingClient, WorkingClient, WorkingCollection


class FlakyCollection:
    """Falla la primera creación de índices y acepta la siguiente."""

    def __init__(self) -> None:
        """Crea una colección que falla la primera vez."""
        self.create_calls = 0
        self.fail = True

    async def create_indexes(self, models: list[object]) -> list[str]:
        """Falla una vez y luego acepta la creación.

        Args:
            models: Modelos de índice que se van a crear.

        Returns:
            La lista de nombres de los índices creados.
        """
        self.create_calls += 1
        if self.fail:
            self.fail = False
            raise OperationFailure("temporary index failure")
        return []


class BlockingCollection:
    """Mantiene la primera creación de índices abierta hasta que el test la libera."""

    def __init__(self) -> None:
        """Crea una colección que bloquea la creación."""
        self.create_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def create_indexes(self, models: list[object]) -> list[str]:
        """Espera antes de crear los índices.

        Args:
            models: Modelos de índice que se van a crear.

        Returns:
            La lista de nombres de los índices creados.
        """
        self.create_calls += 1
        self.started.set()
        await self.release.wait()
        return []


async def test_readiness_pings_every_time_and_creates_indexes_once() -> None:
    """El ping es por sondeo; los índices son estado del proceso."""
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
    """Mongo inalcanzable y índices ausentes son fallos distintos."""
    collection = WorkingCollection()
    probe = ReadinessProbe(FailingClient(), collection, retention_days=0)

    with pytest.raises(AuditStorageError):
        await probe()

    assert probe.indexes_ready is False
    assert collection.create_calls == 0


async def test_indexes_are_retried_after_the_first_attempt_fails() -> None:
    """Un fallo transitorio de creación no puede dejar el servicio en `503`."""
    collection = FlakyCollection()
    probe = ReadinessProbe(WorkingClient(), collection, retention_days=0)

    with pytest.raises(AuditStorageError):
        await probe()

    assert probe.indexes_ready is False

    await probe()

    assert probe.indexes_ready is True
    assert collection.create_calls == 2


async def test_concurrent_readiness_checks_create_indexes_once() -> None:
    """El lock evita que varios `/readyz` creen los índices a la vez."""
    collection = BlockingCollection()
    probe = ReadinessProbe(WorkingClient(), collection, retention_days=0)

    tasks = [asyncio.create_task(probe.ensure_indexes()) for _ in range(3)]
    await asyncio.wait_for(collection.started.wait(), timeout=1)
    await asyncio.sleep(0)
    collection.release.set()
    await asyncio.gather(*tasks)

    assert collection.create_calls == 1
    assert probe.indexes_ready is True
