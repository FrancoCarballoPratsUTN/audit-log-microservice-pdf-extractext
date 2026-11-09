"""Pruebas del orden de los middlewares."""

from starlette.middleware.cors import CORSMiddleware

from app.api.auth import BearerAuthMiddleware
from app.api.middleware.access_log import AccessLogMiddleware
from app.api.middleware.body_size import BodySizeLimitMiddleware
from app.api.middleware.content_type import ContentTypeMiddleware
from app.api.middleware.request_id import RequestIdMiddleware
from app.config import Settings
from tests.unit.api._middleware_common import build_app, create_app

EXPECTED_ORDER = [
    BearerAuthMiddleware,
    RequestIdMiddleware,
    ContentTypeMiddleware,
    BodySizeLimitMiddleware,
    CORSMiddleware,
    AccessLogMiddleware,
]


def test_the_stack_order_is_the_contract_order() -> None:
    """El orden real que construye la fábrica, no el que describe la prosa."""
    app = build_app()

    assert [middleware.cls for middleware in app.user_middleware] == EXPECTED_ORDER


def test_the_factory_builds_the_same_stack(monkeypatch) -> None:
    """Comprueba que la fábrica construye la misma pila de middlewares.

    Args:
        monkeypatch: Utilidad de pytest para sustituir valores.

    Returns:
        No retorna valor.
    """
    for variable in Settings.model_fields:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SERVICE_API_TOKEN", "s3cr3t-shared-token")

    app = create_app()

    assert [middleware.cls for middleware in app.user_middleware] == EXPECTED_ORDER
