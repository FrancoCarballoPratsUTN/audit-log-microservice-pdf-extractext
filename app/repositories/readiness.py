"""Sonda de readiness: Mongo responde y los índices existen.

`/readyz` no puede limitarse a un `ping`: un Mongo que responde pero al que le
faltan los índices de SPEC §6.3 acepta escrituras que luego fallan o devuelven
páginas no deterministas. La sonda separa los dos fallos y mantiene el segundo
en estado del proceso, porque los índices no cambian entre sondeos.

La creación es idempotente y está serializada con un lock: varios `/readyz`
concurrentes no deben lanzar `create_indexes` en paralelo, y un fallo
transitorio debe poder reintentarse en el siguiente sondeo.
"""

import asyncio
from typing import Any

from pymongo import AsyncMongoClient

from app.repositories import mongodb


class ReadinessProbe:
    """Comprobar Mongo e inicializar los índices una sola vez.

    Attributes:
        indexes_ready: `True` cuando `create_indexes` terminó bien en este
            proceso. Un fallo lo deja en `False` para que el próximo sondeo
            vuelva a intentarlo.
    """

    def __init__(
        self,
        client: AsyncMongoClient[mongodb.Document],
        collection: Any,
        *,
        retention_days: int,
    ) -> None:
        """Guardar las dependencias que el composition root ya construyó."""
        self._client = client
        self._collection = collection
        self._retention_days = retention_days
        self._lock = asyncio.Lock()
        self._indexes_ready = False

    @property
    def indexes_ready(self) -> bool:
        """Si los índices ya están listos en este proceso."""
        return self._indexes_ready

    async def __call__(self) -> None:
        """Hacer ping y, si hace falta, crear los índices.

        Raises:
            AuditStorageError: Si Mongo no responde o rechaza los índices. La
                Capa 1 lo traduce a `503`, que es reintentable.
        """
        await mongodb.ping(self._client)
        await self.ensure_indexes()

    async def ensure_indexes(self) -> None:
        """Crear los índices una sola vez, incluso con llamadas concurrentes."""
        if self._indexes_ready:
            return
        async with self._lock:
            if self._indexes_ready:
                return
            await mongodb.ensure_indexes(
                self._collection, retention_days=self._retention_days
            )
            self._indexes_ready = True
