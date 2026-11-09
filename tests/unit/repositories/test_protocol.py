"""Pruebas del contrato del repositorio."""

from app.errors import ServiceError
from app.repositories.protocol import AuditLogRepository, ReplayDetected
from tests.fakes.fake_repository import FakeAuditLogRepository


def test_the_fake_satisfies_the_repository_protocol() -> None:
    """Cumplimiento estructural: el fake no hereda del `Protocol`, sólo implementa sus
    métodos.
    """
    assert isinstance(FakeAuditLogRepository(), AuditLogRepository)


def test_the_replay_signal_is_not_a_service_error() -> None:
    """Un replay responde `200` con el registro existente: si la señal fuera un
    `ServiceError`, la Capa 1 la convertiría en problem details y el Orquestad...
    """
    assert not isinstance(ReplayDetected(), ServiceError)
