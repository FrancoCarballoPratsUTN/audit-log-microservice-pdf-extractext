"""Sondas de liveness y readiness.

`/health` responde «el proceso existe»; `/readyz` responde «puede atender
tráfico». Son preguntas distintas y por eso viven en endpoints distintos: si
`/health` consultara Mongo, una caída de la base mataría el proceso y con él la
única señal que explica el porqué (SPEC §6.5).

Las dos son públicas. La declaración vive en `PUBLIC_PATHS`
(`app/api/auth.py`), no aquí: duplicar la lista en el middleware y en las rutas
sería dos verdades que se desincronizarían.
"""

from fastapi import APIRouter, Request

from app.repositories.mongodb import ping

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: el proceso está vivo")
async def health() -> dict[str, str]:
    """Responder `200` sin tocar Mongo.

    Deliberadamente no consulta nada: un proceso vivo que responde sondas es
    recuperable por el orquestador, y esa respuesta es lo que permite decidirlo.
    """
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness: el servicio puede atender tráfico")
async def readyz(request: Request) -> dict[str, str]:
    """Hacer `ping` y dejar que la Capa 1 traduzca el fallo a `503`.

    El `ping` es de cada llamada y no un flag del arranque, para que una caída
    transitoria de Mongo no deje el servicio en `503` para siempre.

    Raises:
        AuditStorageError: Si Mongo no responde. El handler lo convierte en
            `503 AUDIT_STORAGE_ERROR`.
    """
    await ping(request.app.state.mongo_client)
    return {"status": "ok", "mongo": "ok"}
