"""Pruebas de la estructura y dependencias del paquete."""

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2] / "app"

LAYERS = ("api", "services", "repositories")


def imported_modules(layer: str) -> set[str]:
    """Módulos que importa `app/<layer>`, leídos del código fuente.

    Args:
        layer: Nombre de la capa del paquete.

    Returns:
        El conjunto de módulos importados.
    """
    imported: set[str] = set()
    for source in (APP_DIR / layer).rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module)
    return imported


@pytest.mark.parametrize("layer", LAYERS)
def test_layer_imports_without_error(layer: str) -> None:
    """Comprueba que cada capa del paquete se puede importar.

    Args:
        layer: Nombre de la capa del paquete.

    Returns:
        No retorna valor.
    """
    module = __import__(f"app.{layer}", fromlist=["__doc__"])
    assert module.__doc__, f"app/{layer} debe documentar su responsabilidad"


@pytest.mark.parametrize("layer", ("api", "services"))
def test_upper_layers_do_not_import_pymongo(layer: str) -> None:
    """`pymongo` sólo puede aparecer en Capa 3.

    Args:
        layer: Nombre de la capa del paquete.

    Returns:
        No retorna valor.
    """
    offenders = {
        name for name in imported_modules(layer) if name.split(".")[0] == "pymongo"
    }
    assert not offenders, f"app/{layer} no debe importar pymongo: {offenders}"


def test_api_layer_does_not_import_pymongo_or_repositories() -> None:
    """La Capa 1 no puede conocer el driver ni la Capa 3."""
    imported = imported_modules("api")

    assert not {name for name in imported if name.split(".")[0] == "pymongo"}, (
        f"app/api no debe importar pymongo: {imported}"
    )
    assert not {name for name in imported if name.startswith("app.repositories")}, (
        f"app/api no debe importar app.repositories: {imported}"
    )


def test_repositories_do_not_import_inner_layers() -> None:
    """La dependencia apunta hacia adentro: Capa 3 no conoce Capa 1 ni 2."""
    offenders = {
        name
        for name in imported_modules("repositories")
        if name.startswith(("app.api", "app.services"))
    }
    assert not offenders, (
        f"app/repositories no debe importar hacia adentro: {offenders}"
    )
