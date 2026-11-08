"""Configuración del logging de la aplicación."""

import logging


def configure_logging(level: str) -> None:
    """Configurar el logging raíz una sola vez al arrancar.

    `basicConfig` no hace nada si ya hay handlers; `setLevel` reaplica el nivel
    para que surta efecto aunque ya exista configuración previa.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger().setLevel(level)
