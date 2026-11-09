"""Pruebas del formato estándar de errores."""

import pytest

from app.api.problem import PROBLEM_MEDIA_TYPE, build_problem, problem_response
from app.errors import AuditStorageError, NotFoundError, UnauthorizedError

CANONICAL_MEMBERS = {"type", "title", "status", "detail", "instance", "code"}


@pytest.mark.parametrize(
    ("error", "status"),
    [(UnauthorizedError(), 401), (NotFoundError(), 404), (AuditStorageError(), 503)],
)
def test_problem_carries_the_error_wiring_metadata(
    error: Exception, status: int
) -> None:
    """Comprueba que el problema incluye los datos del error.

    Args:
        error: Error que se va a lanzar o comprobar.
        status: Código de estado HTTP.

    Returns:
        No retorna valor.
    """
    problem = build_problem(error, instance="/audit/logs")

    assert problem.type == error.type_uri
    assert problem.title == error.title
    assert problem.status == status
    assert problem.code == error.code


def test_problem_exposes_exactly_the_six_members() -> None:
    """Comprueba que el problema tiene exactamente seis miembros."""
    problem = build_problem(NotFoundError(), instance="/audit/logs")

    assert set(problem.model_dump()) == CANONICAL_MEMBERS


def test_instance_is_the_request_path() -> None:
    """Comprueba que la instancia es la ruta de la petición."""
    assert build_problem(NotFoundError(), instance="/audit/logs").instance == (
        "/audit/logs"
    )


def test_detail_is_the_specific_occurrence_and_title_stays_generic() -> None:
    """`title` debe seguir siendo comparable entre ocurrencias; `detail` es donde este
    fallo concreto se explica.
    """
    first = build_problem(NotFoundError("No route matches /nope."), instance="/nope")
    second = build_problem(
        NotFoundError("No route matches /audit/logs."), instance="/x"
    )

    assert first.title == second.title
    assert first.detail != second.detail


def test_response_uses_the_problem_media_type() -> None:
    """Comprueba que la respuesta usa el tipo de problema."""
    response = problem_response(NotFoundError(), instance="/audit/logs")

    assert response.media_type == PROBLEM_MEDIA_TYPE


def test_response_carries_the_error_status_code() -> None:
    """Comprueba que la respuesta usa el estado del error."""
    assert (
        problem_response(AuditStorageError(), instance="/audit/logs").status_code == 503
    )


def test_response_includes_the_headers_the_error_requires() -> None:
    """Un `401` sin `WWW-Authenticate` le dice al cliente cómo autenticarse sólo por
    casualidad.
    """
    response = problem_response(UnauthorizedError(), instance="/audit/logs")

    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_response_without_required_headers_sends_none() -> None:
    """Comprueba que una respuesta sin cabeceras obligatorias no las envía."""
    response = problem_response(NotFoundError(), instance="/audit/logs")

    assert "WWW-Authenticate" not in response.headers


def test_response_body_is_valid_json() -> None:
    """Comprueba que el cuerpo de la respuesta es JSON válido."""
    import json

    response = problem_response(NotFoundError("gone"), instance="/audit/logs")

    assert set(json.loads(response.body)) == CANONICAL_MEMBERS
