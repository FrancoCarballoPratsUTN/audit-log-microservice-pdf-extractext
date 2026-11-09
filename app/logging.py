"""Configura los mensajes de registro de la aplicación."""

import logging


def configure_logging(level: str) -> None:
    """Configura el nivel y el formato de los registros.

    Args:
        level: Nivel de registro.

    Returns:
        No retorna valor.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger().setLevel(level)
