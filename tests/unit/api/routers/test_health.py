"""Sondas de salud: la diferencia entre «vivo» y «sirviendo».

`/health` y `/readyz` no hacen la misma pregunta. `/health` responde «el proceso
existe»; `/readyz` responde «puede atender tráfico». Por eso Mongo caído no mata
el proceso: un proceso vivo que responde sondas es recuperable por el orquestador,
un proceso muerto no (SPEC §6.5).

Ambas son públicas (`PUBLIC_PATHS` en `app/api/auth.py`). Un sondeo que exige
credenciales es un sondeo que la plataforma va a marcar como fallido.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pymongo.errors import InvalidOperation

from app.api.auth import PUBLIC_PATHS
from app.api.exception_handlers import register_exception_handlers
from app.api.routers.health import router
from app.config import Settings
from app.main import create_app, lifespan
from tests.fakes.fake_mongo import FailingClient, WorkingClient

TOKEN = "s3cr3t-shared-token"

UNREACHABLE_URI = "mongodb://localhost:59999"


@pytest.fixture(autouse=True)
def only_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deja el entorno limpio salvo el token, para que cada test declare el
    Mongo que necesita."""
    for variable in Settings.model_fields:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SERVICE_API_TOKEN", TOKEN)


@pytest.fixture
def mongo_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apunta `MONGO_URI` a un puerto sin nada detrás, con un timeout corto para
    que el test no espere los 30 s por defecto del driver."""
    monkeypatch.setenv("MONGO_URI", UNREACHABLE_URI)
    monkeypatch.setenv("MONGO_TIMEOUT_MS", "150")


def build_app(client: object) -> FastAPI:
    """App mínima con las sondas y el cliente que se le pase."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.state.mongo_client = client

    @app.get("/audit/logs")
    async def list_logs() -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_health_answers_200_without_touching_mongo() -> None:
    """Liveness no consulta nada: si lo hiciera, una caída de Mongo mataría el
    proceso y con ella la única señal que explica por qué."""
    client = TestClient(build_app(FailingClient()))

    assert client.get("/health").status_code == 200


def test_health_stays_200_when_mongo_raises_on_every_command() -> None:
    """Un doble que revienta en todo es el caso peor, y aun así `/health` no debe
    moverse: para eso existe `/readyz`."""
    client = TestClient(build_app(FailingClient(RuntimeError("Mongo en llamas"))))

    assert client.get("/health").status_code == 200


def test_readyz_reports_ready_when_mongo_answers() -> None:
    client = TestClient(build_app(WorkingClient()))

    assert client.get("/readyz").status_code == 200


def test_readyz_reports_503_when_mongo_does_not_answer() -> None:
    """SPEC §6.5: la app arranca igualmente y es `/readyz` quien reporta `503`."""
    client = TestClient(build_app(FailingClient()))

    assert client.get("/readyz").status_code == 503


def test_the_503_is_a_parseable_problem_and_not_a_bare_status() -> None:
    """El orquestador parsea cualquier `status >= 300` como problem details
    (SPEC §2.6); un 503 con el cuerpo vacío lo degrada a error genérico."""
    response = TestClient(build_app(FailingClient())).get("/readyz")

    assert response.json()["code"] == "AUDIT_STORAGE_ERROR"
    assert response.json()["status"] == 503
    assert response.headers["content-type"].startswith("application/problem+json")


def test_both_probes_are_declared_public() -> None:
    """Declarado una vez, en el módulo de auth: si el middleware y las rutas
    llevaran su propia lista, se desincronizarían."""
    assert {"/health", "/readyz"} <= PUBLIC_PATHS


def test_the_app_starts_even_when_mongo_is_unreachable(mongo_is_down: None) -> None:
    """SPEC §6.5: preferimos un proceso vivo que responde sondas a un proceso
    muerto. Apuntar `MONGO_URI` a un puerto sin nada detrás no debe impedir
    levantar la app."""
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/readyz").status_code == 503


def test_the_probes_need_no_credentials_on_the_real_app(mongo_is_down: None) -> None:
    """La garantía de que las sondas quedan fuera del middleware, sobre la app
    real y no sobre una montada a mano. La ruta protegida da `401` en la misma
    petición para dejar claro que el `401` no llega por otra causa."""
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/readyz").status_code == 503
        assert client.get("/audit/logs").status_code == 401


def test_the_probes_answer_with_credentials_too(mongo_is_down: None) -> None:
    """Una sonda no debe *rechazar* la credencial si llega: `PUBLIC_PATHS` las deja
    pasar, no las pone en una lista negra."""
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        assert client.get("/health", headers=headers).status_code == 200
        assert client.get("/readyz", headers=headers).status_code == 503


def test_readyz_recovers_when_mongo_comes_back(mongo_is_down: None) -> None:
    """`/readyz` se consulta en cada sondeo, no una vez al arrancar: una caída
    transitoria de Mongo no puede dejar el servicio en `503` para siempre. Por eso
    vuelve a hacer `ping` en cada llamada en vez de leer un flag del arranque."""
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/readyz").status_code == 503

        app.state.mongo_client = WorkingClient()

        assert client.get("/readyz").status_code == 200


async def test_the_lifespan_closes_the_client_when_it_exits(
    mongo_is_down: None,
) -> None:
    """Un cliente sin cerrar deja conexiones y *handles* vivos: el proceso no
    termina limpio y cualquier test que abra y cierre apps va acumulando sockets
    hasta que el sistema de ficheros se queja.

    Se comprueba por la vía pública del driver: un `AsyncMongoClient` cerrado lanza
    `InvalidOperation` ante cualquier uso. No hace falta tocar `_closed`. El
    `lifespan` se invoca directamente para poder comprobarlo en el mismo event
    loop del test: un `AsyncMongoClient` atado a un loop no puede usarse desde otro.
    """
    app = create_app()

    async with lifespan(app):
        assert app.state.mongo_client is not None

    with pytest.raises(InvalidOperation):
        await app.state.mongo_client.admin.command("ping")


def test_the_app_refuses_to_build_without_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El orden de §6.5 es «resolver, luego abrir»: sin token no hay cliente que
    abrir, y `create_app` lo vigila antes de tocar Mongo."""
    monkeypatch.delenv("SERVICE_API_TOKEN", raising=False)

    with pytest.raises(ValidationError, match="service_api_token"):
        create_app()
