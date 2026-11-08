"""Comunes para los tests de `POST /audit/logs` (divididos de test_create_audit_log.py).

No se recolecta como test por empezar con guion bajo.
"""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.integration.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}

VALID_EVENT = {
    "action": "pdf.extract",
    "entity_type": "document",
    "checksum": "9f86d081884c7d659a2feaa0c55ad015",
    "details": {"page_count": 12},
    "performed_at": "2026-10-05T12:34:56.789Z",
}

RAW_EVENT_PREFIX = (
    '{"action":"pdf.extract","entity_type":"document",'
    '"checksum":"9f86d081884c7d659a2feaa0c55ad015",'
    '"performed_at":"2026-10-05T12:34:56.789Z","details":'
)


def app_client() -> TestClient:
    return TestClient(create_app())
