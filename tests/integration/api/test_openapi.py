"""T16: el contrato que `/openapi.json` publica.

El comportamiento ya está probado; lo que se afirma aquí es que el documento
**publicado** no miente. Tres mentiras concretas rompen al orquestador o a quien
integra: un `Bearer` que no aparece y deja a `/docs` sin forma de enviar el token;
un `id` donde el modelo de Go espera `_id` (SPEC §2.5 H3), y un `422` que este
servicio no sabe emitir y que el cliente leería como problem vacío (SPEC §2.6).
"""

import pytest

from app.main import create_app

AUDIT_OPERATIONS = [
    ("/audit/logs", "post"),
    ("/audit/logs", "get"),
    ("/audit/logs/checksum/{checksum}", "get"),
]

HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


def test_the_bearer_scheme_is_http_bearer(deployed: None) -> None:
    """El candado que /docs dibuja es un HTTP bearer, no un apiKey suelto."""
    spec = create_app().openapi()

    scheme = spec["components"]["securitySchemes"]["Bearer"]
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"


@pytest.mark.parametrize(("path", "method"), AUDIT_OPERATIONS)
def test_every_audit_operation_requires_bearer(
    deployed: None, path: str, method: str
) -> None:
    """Las 3 rutas de auditoría declaran el requisito de seguridad (SPEC §4)."""
    operation = create_app().openapi()["paths"][path][method]

    assert {"Bearer": []} in operation.get("security", [])


def test_the_public_probes_carry_no_security(deployed: None) -> None:
    """`/health` y `/readyz` son públicas (SPEC §6.5): /docs no debe pedir token."""
    spec = create_app().openapi()

    for path in ("/health", "/readyz"):
        assert not spec["paths"][path]["get"].get("security")


def test_response_schemas_declare_id_not_id(deployed: None) -> None:
    """`_id` es el nombre del contrato (SPEC §2.4): si el schema dice `id`, el
    `ID string` de Go se queda vacío sin error visible."""
    schemas = create_app().openapi()["components"]["schemas"]

    for name in ("AuditLogItem", "AuditLogResponse"):
        properties = schemas[name]["properties"]
        assert "_id" in properties
        assert "id" not in properties


def test_no_operation_documents_422(deployed: None) -> None:
    """Ningún `422` en el documento (SPEC §2.6): el handler lo convierte en `400`,
    así que publicarlo sería documentar una respuesta que no existe."""
    spec = create_app().openapi()

    offenders = [
        (path, method)
        for path, operations in spec["paths"].items()
        for method, operation in operations.items()
        if method in HTTP_METHODS and "422" in operation["responses"]
    ]

    assert offenders == []
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_post_documents_its_whole_error_contract(deployed: None) -> None:
    """`POST /audit/logs` publica `201` y las cuatro filas de error que puede
    devolver (SPEC §7.2)."""
    responses = create_app().openapi()["paths"]["/audit/logs"]["post"]["responses"]

    assert {"201", "400", "401", "413", "415"} <= set(responses)
