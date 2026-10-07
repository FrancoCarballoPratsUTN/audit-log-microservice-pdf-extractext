"""Cuerpos RFC 9457.

`app/api/problem.py` es el único sitio que convierte un error de dominio en
bytes. El cliente de Go parsea todo cuerpo con `status >= 300` esperando `type`,
`title`, `status` y `detail` (SPEC §2.6); un 500 en texto plano lo degradaría a un
error genérico y el orquestador respondería `502`.
"""

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
    problem = build_problem(error, instance="/audit/logs")

    assert problem.type == error.type_uri
    assert problem.title == error.title
    assert problem.status == status
    assert problem.code == error.code


def test_problem_exposes_exactly_the_six_members() -> None:
    problem = build_problem(NotFoundError(), instance="/audit/logs")

    assert set(problem.model_dump()) == CANONICAL_MEMBERS


def test_instance_is_the_request_path() -> None:
    assert build_problem(NotFoundError(), instance="/audit/logs").instance == (
        "/audit/logs"
    )


def test_detail_is_the_specific_occurrence_and_title_stays_generic() -> None:
    """`title` debe seguir siendo comparable entre ocurrencias; `detail` es donde
    este fallo concreto se explica (SPEC §7.1)."""
    first = build_problem(NotFoundError("No route matches /nope."), instance="/nope")
    second = build_problem(
        NotFoundError("No route matches /audit/logs."), instance="/x"
    )

    assert first.title == second.title
    assert first.detail != second.detail


def test_response_uses_the_problem_media_type() -> None:
    response = problem_response(NotFoundError(), instance="/audit/logs")

    assert response.media_type == PROBLEM_MEDIA_TYPE


def test_response_carries_the_error_status_code() -> None:
    assert (
        problem_response(AuditStorageError(), instance="/audit/logs").status_code == 503
    )


def test_response_includes_the_headers_the_error_requires() -> None:
    """RFC 9110 §15.5.2: un `401` sin `WWW-Authenticate` le dice al cliente cómo
    autenticarse sólo por casualidad."""
    response = problem_response(UnauthorizedError(), instance="/audit/logs")

    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_response_without_required_headers_sends_none() -> None:
    response = problem_response(NotFoundError(), instance="/audit/logs")

    assert "WWW-Authenticate" not in response.headers


def test_response_body_is_valid_json() -> None:
    import json

    response = problem_response(NotFoundError("gone"), instance="/audit/logs")

    assert set(json.loads(response.body)) == CANONICAL_MEMBERS
