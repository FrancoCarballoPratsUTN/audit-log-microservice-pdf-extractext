"""Entrega el servicio de auditoría a las rutas."""

from fastapi import Request

from app.services.audit_log_service import AuditLogService


def get_audit_log_service(request: Request) -> AuditLogService:
    """Obtiene el servicio de auditoría de la aplicación.

    Args:
        request: Petición HTTP recibida.

    Returns:
        El servicio configurado al arrancar.
    """
    return request.app.state.audit_log_service
