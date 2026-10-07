"""El puerto `AuditLogRepository` y la señal de replay.

El protocolo no tiene comportamiento que probar, pero sí dos garantías que se
perderían en silencio si alguien las tocara: que el doble de memoria cumple el
contrato sin herencia (que es lo que permite sustituirlo en los tests de T9 y
T11), y que la señal de replay no es un error de dominio con código HTTP.
"""

from app.errors import ServiceError
from app.repositories.protocol import AuditLogRepository, ReplayDetected
from tests.fakes.fake_repository import FakeAuditLogRepository


def test_the_fake_satisfies_the_repository_protocol() -> None:
    """Cumplimiento estructural: el fake no hereda del `Protocol`, sólo
    implementa sus métodos. Si alguien renombra uno de los cinco, el
    `runtime_checkable` lo delata aquí y no en el ensamblaje de T9."""
    assert isinstance(FakeAuditLogRepository(), AuditLogRepository)


def test_the_replay_signal_is_not_a_service_error() -> None:
    """Un replay responde `200` con el registro existente (SPEC §5.3): si la
    señal fuera un `ServiceError`, la Capa 1 la convertiría en problem details
    y el Orquestador vería un fallo donde hubo una repetición benigna."""
    assert not isinstance(ReplayDetected(), ServiceError)
