"""Estructura del paquete y dirección de dependencias.

La arquitectura de 3 capas no se sostiene por disciplina: es una restricción que
se rompe en silencio. Un `from pymongo import ...` en `app/api/` compila, pasa
los tests, y acopla la Capa 1 al driver. Estos tests fallan el día que alguien
lo importa.

Se inspecciona el código fuente con `ast` en vez de leer `sys.modules`: el estado
de los módulos ya importados no distingue "esta capa importa pymongo" de "otra
capa lo importó antes que yo".
"""

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2] / "app"

LAYERS = ("api", "services", "repositories")


def imported_modules(layer: str) -> set[str]:
    """Módulos que importa `app/<layer>`, leídos del código fuente."""
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
    module = __import__(f"app.{layer}", fromlist=["__doc__"])
    assert module.__doc__, f"app/{layer} debe documentar su responsabilidad"


@pytest.mark.parametrize("layer", ("api", "services"))
def test_upper_layers_do_not_import_pymongo(layer: str) -> None:
    """`pymongo` sólo puede aparecer en Capa 3."""
    offenders = {
        name for name in imported_modules(layer) if name.split(".")[0] == "pymongo"
    }
    assert not offenders, f"app/{layer} no debe importar pymongo: {offenders}"


def test_audit_logs_router_does_not_import_pymongo_or_repositories() -> None:
    """AC de T10: la Capa 1 no puede conocer el driver ni Capa 3. El router
    pide el servicio por dependency injection (`app.state`), no lo construye."""
    source = (APP_DIR / "api" / "routers" / "audit_logs.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)

    assert not any(name == "pymongo" or name == "pymongo.errors" for name in imported)
    assert not any(name.startswith("app.repositories") for name in imported)


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
