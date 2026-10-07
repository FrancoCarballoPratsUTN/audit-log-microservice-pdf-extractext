"""Jerarquía de errores y su matriz de cable.

La matriz de SPEC §7.2 está **reescrita a mano aquí** en vez de importarse de
`app.errors`. La duplicación es el mecanismo de detección: si alguien añade una
novena excepción, o cambia un `status`, el test se pone rojo porque esta tabla
sigue diciendo lo que dice el diseño. Un guard que leyera su propia verdad del
código no detectaría nada.

`title` nunca lleva valores variables (SPEC §7.1): los clientes comparan
errores por `title`, así que el mismo error debe dar siempre el mismo texto.
"""

import ast
from pathlib import Path

import pytest

from app.errors import (
    AuditStorageError,
    InternalError,
    MethodNotAllowedError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceError,
    UnauthorizedError,
    UnsupportedMediaTypeError,
    ValidationError,
)

ERRORS_SOURCE = Path(__file__).resolve().parents[2] / "app" / "errors.py"

# (clase, status, code, type, title) -- SPEC §7.2, fila por fila.
SPEC_ERROR_MATRIX: list[tuple[type[ServiceError], int, str, str, str]] = [
    (UnauthorizedError, 401, "UNAUTHORIZED", "/problems/unauthorized", "Unauthorized"),
    (
        ValidationError,
        400,
        "VALIDATION_ERROR",
        "/problems/validation_error",
        "Request validation error",
    ),
    (NotFoundError, 404, "NOT_FOUND", "/problems/not_found", "Resource not found"),
    (
        MethodNotAllowedError,
        405,
        "METHOD_NOT_ALLOWED",
        "/problems/method_not_allowed",
        "Method not allowed",
    ),
    (
        PayloadTooLargeError,
        413,
        "PAYLOAD_TOO_LARGE",
        "/problems/payload_too_large",
        "Payload too large",
    ),
    (
        UnsupportedMediaTypeError,
        415,
        "UNSUPPORTED_MEDIA_TYPE",
        "/problems/unsupported_media_type",
        "Unsupported media type",
    ),
    (
        InternalError,
        500,
        "INTERNAL_ERROR",
        "/problems/internal_error",
        "Internal server error",
    ),
    (
        AuditStorageError,
        503,
        "AUDIT_STORAGE_ERROR",
        "/problems/audit_storage_error",
        "Audit storage unavailable",
    ),
]

MATRIX_IDS = [row[0].__name__ for row in SPEC_ERROR_MATRIX]


def test_matrix_has_the_eight_rows_of_the_spec() -> None:
    """SPEC §7.2 tiene ocho filas, ni una más ni una menos."""
    assert len(SPEC_ERROR_MATRIX) == 8


@pytest.mark.parametrize(
    ("error_class", "status", "code", "type_uri", "title"),
    SPEC_ERROR_MATRIX,
    ids=MATRIX_IDS,
)
def test_error_declares_its_wiring_metadata(
    error_class: type[ServiceError],
    status: int,
    code: str,
    type_uri: str,
    title: str,
) -> None:
    assert error_class.status == status
    assert error_class.code == code
    assert error_class.type_uri == type_uri
    assert error_class.title == title


def test_type_uris_are_unique_across_the_matrix() -> None:
    """`type` es el identificador del problema en RFC 9457 §3.1. Dos filas con
    el mismo `type` serían indistinguibles para el cliente."""
    type_uris = [row[3] for row in SPEC_ERROR_MATRIX]
    assert len(set(type_uris)) == len(type_uris)


def test_no_error_class_exists_outside_the_spec_matrix() -> None:
    """Guard de drift: una excepción nueva sin fila en SPEC §7.2."""
    declared = {subclass.__name__ for subclass in ServiceError.__subclasses__()}
    assert declared == set(MATRIX_IDS)


def test_no_spec_row_is_left_without_an_implementation() -> None:
    """Guard de drift en el otro sentido: una fila de SPEC sin clase."""
    declared = {subclass.__name__ for subclass in ServiceError.__subclasses__()}
    assert set(MATRIX_IDS) <= declared


def test_wiring_metadata_lives_on_the_class_not_on_the_instance() -> None:
    """`status`, `code`, `type_uri` y `title` son `ClassVar`. Si vivieran en la
    instancia, dos `ValidationError` distintos podrían decir cosas distintas y
    el cliente no podría compararlos por `title`."""
    error = ValidationError("something specific went wrong")
    for attribute in ("status", "code", "type_uri", "title"):
        assert attribute not in vars(error)


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


def test_only_unauthorized_declares_response_headers() -> None:
    """`WWW-Authenticate` es lo único que RFC 9110 §15.5.2 exige. Los otros siete
    errores no necesitan cabeceras propias."""
    with_headers = [
        subclass.__name__
        for subclass in ServiceError.__subclasses__()
        if subclass.headers is not None
    ]
    assert with_headers == ["UnauthorizedError"]


def test_unauthorized_declares_the_www_authenticate_challenge() -> None:
    assert UnauthorizedError.headers == {"WWW-Authenticate": "Bearer"}


def test_errors_without_response_headers_declare_none() -> None:
    """Se declara explícitamente para que el handler pueda leer `error.headers`
    sin un `getattr` defensivo."""
    assert ValidationError.headers is None


def test_service_error_is_catchable_as_a_plain_exception() -> None:
    """El catch-all de T3 distingue un error de dominio de una excepción
    cualquiera por la jerarquía, no por un `isinstance` por subclase."""
    with pytest.raises(ServiceError):
        raise AuditStorageError("storage is unreachable")


def test_errors_module_does_not_import_the_web_framework() -> None:
    """`errors.py` es dominio puro: la Capa 3 lo lanza y la Capa 1 lo traduce.
    Un import de FastAPI aquí invertiría la dirección de la dependencia."""
    tree = ast.parse(ERRORS_SOURCE.read_text(encoding="utf-8"))
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
