"""Simula MongoDB para las pruebas."""

from pymongo.errors import OperationFailure, ServerSelectionTimeoutError


class WorkingAdmin:
    """`admin` que responde al `ping` como responde Mongo."""

    def __init__(self) -> None:
        """Crea el administrador falso y su lista de pings."""
        self.pings: list[str] = []

    async def command(self, name: str) -> dict[str, float]:
        """Registra el comando y responde como MongoDB.

        Args:
            name: Nombre del comando o recurso.

        Returns:
            La respuesta del comando.
        """
        self.pings.append(name)
        return {"ok": 1.0}


class WorkingClient:
    """Cliente cuyo Mongo responde."""

    def __init__(self) -> None:
        """Crea el cliente falso con su administrador."""
        self.admin = WorkingAdmin()
        self.closed = False

    async def close(self) -> None:
        """Cierra el cliente falso sin hacer nada."""
        self.closed = True


class FailingClient:
    """Cliente que lanza la excepción del driver que se le pase en cada comando.

    Sirve para los dos papeles distintos que necesita el lifespan: Mongo que no
    responde a `ping` (error de selección) y Mongo que responde pero falla una
    operación posterior (error de escritura).
    """

    def __init__(self, error: Exception | None = None) -> None:
        """Crea un cliente falso que lanza el error indicado.

        Args:
            error: Error que se va a lanzar o comprobar.

        Returns:
            No retorna valor.
        """
        self.error = error or ServerSelectionTimeoutError("timed out")
        self.commands: list[str] = []
        self.closed = False

    @property
    def admin(self) -> FailingAdmin:
        """Devuelve el administrador que lanza el error."""
        return FailingAdmin(self)

    async def close(self) -> None:
        """Cierra el cliente falso sin hacer nada."""
        self.closed = True


class FailingAdmin:
    def __init__(self, client: FailingClient) -> None:
        """Guarda el cliente que lanzará el error.

        Args:
            client: Cliente que usa la prueba.

        Returns:
            No retorna valor.
        """
        self.client = client

    async def command(self, name: str) -> dict[str, float]:
        """Lanza el error configurado al ejecutar un comando.

        Args:
            name: Nombre del comando o recurso.

        Returns:
            No retorna valor.
        """
        self.client.commands.append(name)
        raise self.client.error


class WorkingCollection:
    """Colección que acepta `create_indexes` y cuenta las llamadas.

    La readiness sólo debe crear índices una vez aunque se sondee muchas veces;
    contar las llamadas es la forma de afirmarlo sin abrir Mongo.
    """

    def __init__(self) -> None:
        """Crea una colección falsa vacía."""
        self.create_calls = 0
        self.models: list[object] = []

    async def create_indexes(self, models: list[object]) -> list[str]:
        """Registra los índices que se intentan crear.

        Args:
            models: Modelos de índice que se van a crear.

        Returns:
            La lista de nombres de los índices creados.
        """
        self.create_calls += 1
        self.models = list(models)
        return [model.document["name"] for model in self.models]


class FailingCollection:
    """Colección que rechaza la creación de índices con el error que se le pase."""

    def __init__(self, error: Exception | None = None) -> None:
        """Guarda el error que lanzará la colección.

        Args:
            error: Error que se va a lanzar o comprobar.

        Returns:
            No retorna valor.
        """
        self.error = error or OperationFailure("indexes could not be created")
        self.create_calls = 0

    async def create_indexes(self, models: list[object]) -> list[str]:
        """Lanza el error configurado al crear índices.

        Args:
            models: Modelos de índice que se van a crear.

        Returns:
            No retorna valor.
        """
        self.create_calls += 1
        raise self.error
