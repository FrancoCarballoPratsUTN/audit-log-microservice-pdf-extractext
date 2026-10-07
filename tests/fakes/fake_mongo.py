"""Dobles de MongoDB para los tests.

`WorkingClient` y `FailingClient` implementan la parte de `AsyncMongoClient` que
el lifespan y `/readyz` usan, que es `client.admin.command("ping")`. Se prefieren
a `unittest.mock` porque tienen comportamiento: el `ping` correcto devuelve
`{"ok": 1.0}` como Mongo, y el que falla lanza la excepción real del driver.

No incluyen `ping` de PyMongo porque ese es justamente el código bajo test
(`app/repositories/mongodb.py`): un doble que replicara el comportamiento real
probaría el doble, no el código.

El `client.close()` es un no-op: no hay conexión que cerrar, y sin él el cierre
del lifespan fallaría contra un doble que no imita esa parte.
"""

from pymongo.errors import ServerSelectionTimeoutError


class WorkingAdmin:
    """`admin` que responde al `ping` como responde Mongo."""

    def __init__(self) -> None:
        self.pings: list[str] = []

    async def command(self, name: str) -> dict[str, float]:
        self.pings.append(name)
        return {"ok": 1.0}


class WorkingClient:
    """Cliente cuyo Mongo responde."""

    def __init__(self) -> None:
        self.admin = WorkingAdmin()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FailingClient:
    """Cliente que lanza la excepción del driver que se le pase en cada comando.

    Sirve para los dos papeles distintos que necesita el lifespan: Mongo que no
    responde a `ping` (error de selección) y Mongo que responde pero falla una
    operación posterior (error de escritura).
    """

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or ServerSelectionTimeoutError("timed out")
        self.commands: list[str] = []
        self.closed = False

    @property
    def admin(self) -> FailingAdmin:
        return FailingAdmin(self)

    async def close(self) -> None:
        self.closed = True


class FailingAdmin:
    def __init__(self, client: FailingClient) -> None:
        self.client = client

    async def command(self, name: str) -> dict[str, float]:
        self.client.commands.append(name)
        raise self.client.error
