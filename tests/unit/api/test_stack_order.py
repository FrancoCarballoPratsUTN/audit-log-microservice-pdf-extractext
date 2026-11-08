"""Orden real del stack de middlewares.

El orden se resuelve en un único sitio: `install_middleware`.
"""

from fastapi import FastAPI

from app.api.auth import BearerAuthMiddleware
from app.config import Settings
from app.api.middleware.access_log import AccessLogMiddleware
from app.api.middleware.body_size import BodySizeLimitMiddleware
from app.api.middleware.content_type import ContentTypeMiddleware
from app.api.middleware.request_id import RequestIdMiddleware
from starlette.middleware.cors import CORSMiddleware

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
    for variable in Settings.model_fields:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SERVICE_API_TOKEN", "s3cr3t-shared-token")

    app = create_app()

    assert [middleware.cls for middleware in app.user_middleware] == EXPECTED_ORDER
