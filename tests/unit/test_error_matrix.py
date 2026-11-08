"""Matriz de errores SPEC §7.2: ocho filas, ni una más ni una menos."""

import pytest

from tests.unit._errors_common import (
    MATRIX_IDS,
    ServiceError,
    SPEC_ERROR_MATRIX,
)


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
