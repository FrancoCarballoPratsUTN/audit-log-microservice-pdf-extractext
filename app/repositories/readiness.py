"""Comprueba MongoDB y crea los índices necesarios."""

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
        """Guarda las dependencias que usará la comprobación.

        Args:
            client: Cliente que usa la prueba.
            collection: Colección de MongoDB.
            retention_days: Días que se conservan los registros.

        Returns:
            No retorna valor.
        """
        self._client = client
        self._collection = collection
        self._retention_days = retention_days
        self._lock = asyncio.Lock()
        self._indexes_ready = False

    @property
    def indexes_ready(self) -> bool:
        """Indica si los índices ya se crearon."""
        return self._indexes_ready

    async def __call__(self) -> None:
        """Comprueba MongoDB y crea los índices si hace falta."""
        await mongodb.ping(self._client)
        await self.ensure_indexes()

    async def ensure_indexes(self) -> None:
        """Crea los índices una sola vez aunque haya varias llamadas."""
        if self._indexes_ready:
            return
        async with self._lock:
            if self._indexes_ready:
                return
            await mongodb.ensure_indexes(
                self._collection, retention_days=self._retention_days
            )
            self._indexes_ready = True
