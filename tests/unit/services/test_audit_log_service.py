"""Pruebas del servicio de auditoría."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import AuditLog, CreateAuditLogRequest
from app.errors import AuditStorageError
from app.repositories.protocol import ReplayDetected
from app.services.audit_log_service import AuditLogService, CreateResult
from tests.fakes.fake_repository import FakeAuditLogRepository

PERFORMED_AT = datetime(2026, 10, 5, 12, 34, 56, 789000, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 10, 5, 12, 34, 57, 41000, tzinfo=UTC)
CHECKSUM = "9f86d081884c7d659a2feaa0c55ad015"
WIRE_ID = "68e2c1f4a1b2c3d4e5f60718"


def make_request(**overrides: object) -> CreateAuditLogRequest:
    """Petición válida, con lo que pida el test cambiado.

    Args:
        **overrides: Argumentos adicionales.

    Returns:
        El objeto creado para la prueba.
    """
    values: dict[str, object] = {
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
        "performed_at": PERFORMED_AT,
    }
    values.update(overrides)
    return CreateAuditLogRequest(**values)


def make_log(**overrides: object) -> AuditLog:
    """Registro ya almacenado con la misma identidad que `make_request()`.

    Args:
        **overrides: Argumentos adicionales.

    Returns:
        El objeto creado para la prueba.
    """
    values: dict[str, object] = {
        "id": WIRE_ID,
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": CHECKSUM,
        "performed_at": PERFORMED_AT,
        "received_at": RECEIVED_AT,
        "details": {"page_count": 12},
    }
    values.update(overrides)
    return AuditLog(**values)


async def test_a_stored_event_is_returned_as_a_replay_without_inserting() -> None:
    """Con el evento ya en la Barrera 1, el resultado es el registro existente y
    `insert` no llega a invocarse.
    """
    stored = make_log()
    fake = FakeAuditLogRepository(items=[stored])
    service = AuditLogService(fake)

    result = await service.create(make_request())

    assert result == CreateResult(stored, replay=True)
    assert fake.insert_calls == 0


async def test_the_replay_path_invokes_the_read_exactly_once() -> None:
    """La Barrera 1 se consulta, se decide y se responde: no hay relecturas ni llamadas
    de escritura de por medio.
    """
    fake = FakeAuditLogRepository(items=[make_log()])
    service = AuditLogService(fake)

    result = await service.create(make_request())

    assert result.replay is True
    assert fake.find_replay_calls == 1
    assert fake.insert_calls == 0


async def test_a_new_event_is_inserted_and_reported_as_created() -> None:
    """Sin evento previo: una lectura de Barrera 1, una escritura, y el log devuelto es
    exactamente el que se insertó.
    """
    fake = FakeAuditLogRepository()
    service = AuditLogService(fake)
    request = make_request(details={"page_count": 12})

    result = await service.create(request)

    assert result.replay is False
    assert result.log.action == request.action
    assert result.log.entity_type == request.entity_type
    assert result.log.checksum == request.checksum
    assert result.log.performed_at == request.performed_at
    assert result.log.details == request.details
    assert fake.insert_calls == 1
    assert fake.find_replay_calls == 1


async def test_received_at_is_server_clock_and_performed_at_keeps_its_instant() -> None:
    """`received_at` es el reloj del servidor, no el del emisor; y `performed_at`
    conserva el instante del emisor, ya normalizado a ms.
    """
    fake = FakeAuditLogRepository()
    service = AuditLogService(fake)
    request = make_request()

    result = await service.create(request)

    assert abs((datetime.now(UTC) - result.log.received_at).total_seconds()) < 5
    assert result.log.performed_at == request.performed_at


class RacingFake:
    """La carrera de §5.3: la primera lectura ve `None`, el índice único
    rechaza la escritura y la relectura devuelve al ganador."""

    def __init__(self, winner: AuditLog) -> None:
        """Crea un repositorio falso con un ganador preparado.

        Args:
            winner: Registro que ya existía.

        Returns:
            No retorna valor.
        """
        self._winner = winner
        self._reads = 0

    async def find_replay(
        self,
        *,
        action: str,
        entity_type: str,
        checksum: str,
        performed_at: datetime,
    ) -> AuditLog | None:
        """Devuelve el ganador en la segunda lectura.

        Args:
            action: Acción realizada.
            entity_type: Tipo de entidad afectada.
            checksum: Valor que identifica el contenido.
            performed_at: Fecha y hora en que ocurrió el evento.

        Returns:
            El documento encontrado o None.
        """
        self._reads += 1
        return None if self._reads == 1 else self._winner

    async def insert(self, request: CreateAuditLogRequest) -> AuditLog:
        """Lanza la señal de que el evento ya existía.

        Args:
            request: Petición HTTP recibida.

        Returns:
            No retorna valor.
        """
        raise ReplayDetected()


async def test_a_duplicate_signal_produces_the_same_replay_result() -> None:
    """Cuando el índice único gana por la mínima, la señal sale del servicio como el
    **mismo** resultado observable que la Barrera 1 —el log ex...
    """
    winner = make_log()
    service = AuditLogService(RacingFake(winner))

    result = await service.create(make_request())

    assert result == CreateResult(winner, replay=True)


class PhantomFake:
    """El índice rechaza la identidad pero la relectura no la encuentra:
    almacenamiento incoherente. Defensivo —debería ser imposible— pero define
    un comportamiento en vez de un `AttributeError` críptico."""

    async def find_replay(
        self,
        *,
        action: str,
        entity_type: str,
        checksum: str,
        performed_at: datetime,
    ) -> AuditLog | None:
        """Devuelve None en la primera y la segunda lectura.

        Args:
            action: Acción realizada.
            entity_type: Tipo de entidad afectada.
            checksum: Valor que identifica el contenido.
            performed_at: Fecha y hora en que ocurrió el evento.

        Returns:
            No retorna valor.
        """
        return None

    async def insert(self, request: CreateAuditLogRequest) -> AuditLog:
        """Lanza la señal de que el evento ya existía.

        Args:
            request: Petición HTTP recibida.

        Returns:
            No retorna valor.
        """
        raise ReplayDetected()


async def test_a_duplicate_that_cannot_be_read_back_is_a_storage_error() -> None:
    """Si el índice dijo «ya existe» y la relectura no lo encuentra, el almacenamiento
    no es fiable: `503` reintentable, no un `500` que se esconde ni un...
    """
    with pytest.raises(AuditStorageError):
        await AuditLogService(PhantomFake()).create(make_request())


async def test_list_page_returns_the_requested_slice_from_the_repository() -> None:
    """La Capa 2 traslada la página ya validada por Capa 1 a Capa 3 sin recortarla ni
    reordenarla —quien corta y ordena es el repositorio—.
    """
    newer = make_log(
        id="000000000000000000000002",
        performed_at=PERFORMED_AT,
    )
    older = make_log(
        id="000000000000000000000001",
        performed_at=PERFORMED_AT - timedelta(days=1),
    )
    service = AuditLogService(FakeAuditLogRepository(items=[older, newer]))

    page = await service.list_page(skip=1, limit=1)

    assert [log.id for log in page] == [older.id]


async def test_list_by_checksum_returns_only_the_repository_matches() -> None:
    """La Capa 2 delega el filtro en el repositorio —filtrar y ordenar es
    responsabilidad de la Capa 3, respaldada por el índice compuesto de §...
    """
    wanted = make_log(id="000000000000000000000001", checksum=CHECKSUM)
    other = make_log(id="000000000000000000000002", checksum="otro-checksum")
    service = AuditLogService(FakeAuditLogRepository(items=[wanted, other]))

    matches = await service.list_by_checksum(CHECKSUM)

    assert [log.id for log in matches] == [wanted.id]
    assert all(log.checksum == CHECKSUM for log in matches)
