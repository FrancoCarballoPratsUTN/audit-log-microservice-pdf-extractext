"""Comportamiento de los errores de dominio."""

import pytest

from tests.unit._errors_common import (
    AuditStorageError,
    ServiceError,
    SPEC_ERROR_MATRIX,
    UnauthorizedError,
    ValidationError,
    NotFoundError,
)


def test_audit_storage_error_is_503_not_500() -> None:
    """`503` y no `500`: MongoDB caído es infraestructura, y el Orquestador
    puede reintentarlo. Un `500` le quitaría esa opción (SPEC §6.4)."""
    assert AuditStorageError.status == 503


def test_detail_falls_back_to_the_class_default() -> None:
    assert ValidationError().detail == ValidationError.default_detail


def test_detail_can_be_overridden_with_the_specific_occurrence() -> None:
    error = ValidationError("Field 'performed_at' is required.")
    assert error.detail == "Field 'performed_at' is required."
    assert error.detail != ValidationError.default_detail


def test_str_carries_the_detail_and_the_class_name() -> None:
    rendered = str(NotFoundError("No route matches /audit/logs."))
    assert rendered == "NotFoundError: No route matches /audit/logs."


def test_default_details_do_not_leak_the_driver_or_a_stack_trace() -> None:
    """`detail` es texto para el cliente (SPEC §7.1). Un default que hablara de
    MongoDB convertiría un fallo de infraestructura en una fuga de detalle."""
    for error_class, *_ in SPEC_ERROR_MATRIX:
        detail = error_class.default_detail.lower()
        assert "mongo" not in detail
        assert "pymongo" not in detail
        assert "traceback" not in detail


def test_service_error_is_catchable_as_a_plain_exception() -> None:
    """El catch-all de T3 distingue un error de dominio de una excepción
    cualquiera por la jerarquía, no por un `isinstance` por subclase."""
    with pytest.raises(ServiceError):
        raise AuditStorageError("storage is unreachable")


def test_errors_module_does_not_import_the_web_framework() -> None:
    """`errors.py` es dominio puro: la Capa 3 lo lanza y la Capa 1 lo traduce.
    Un import de FastAPI aquí invertiría la dirección de la dependencia."""
    from pathlib import Path
    import ast

    source = Path(__file__).resolve().parents[2] / "app" / "errors.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)

    frameworks = {
        name
        for name in imported
        if name.split(".")[0] in {"fastapi", "starlette", "pymongo"}
    }
    assert not frameworks, f"app/errors.py no debe importar el framework: {frameworks}"
