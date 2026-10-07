"""Inyección de dependencias de la Capa 1.

El router no construye nada: pide el servicio a `app.state`, donde el composition
root lo dejó al arrancar. Así ni el router ni sus tests tienen que saber cómo se
monta el repositorio ni el driver (SPEC §12), y la Capa 1 sigue sin importar
`pymongo` ni `app.repositories`.
"""

from fastapi import Request

from app.services.audit_log_service import AuditLogService


def get_audit_log_service(request: Request) -> AuditLogService:
    """El servicio de escritura cableado por `app.main` en el lifespan.

    Args:
        request: La petición en curso; porta `app.state`.

    Returns:
        La instancia que el composition root dejó al arrancar.
    """
    return request.app.state.audit_log_service
