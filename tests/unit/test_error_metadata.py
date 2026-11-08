"""Metadatos de cable de cada error: status, code, type_uri, title, headers."""

from tests.unit._errors_common import (
    ServiceError,
    UnauthorizedError,
    ValidationError,
)


def test_wiring_metadata_lives_on_the_class_not_on_the_instance() -> None:
    """`status`, `code`, `type_uri` y `title` son `ClassVar`. Si vivieran en la
    instancia, dos `ValidationError` distintos podrían decir cosas distintas y
    el cliente no podría compararlos por `title`."""
    error = ValidationError("something specific went wrong")
    for attribute in ("status", "code", "type_uri", "title"):
        assert attribute not in vars(error)


def test_only_unauthorized_declares_response_headers() -> None:
    """`WWW-Authenticate` es lo único que RFC 9110 §15.5.2 exige. Los otros
    siete errores no necesitan cabeceras propias."""
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
