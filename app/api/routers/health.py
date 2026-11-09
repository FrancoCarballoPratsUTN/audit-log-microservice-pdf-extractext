"""Rutas para comprobar la salud del servicio."""

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: el proceso está vivo")
async def health() -> dict[str, str]:
    """Indica que el proceso está vivo."""
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness: el servicio puede atender tráfico")
async def readyz(request: Request) -> dict[str, str]:
    """Indica si el servicio puede atender peticiones.

    Args:
        request: Petición HTTP recibida.

    Returns:
        El estado del servicio y de MongoDB.

    Raises:
        AuditStorageError: Si MongoDB o los índices no están disponibles.
    """
    await request.app.state.readiness_probe()
    return {"status": "ok", "mongo": "ok"}
