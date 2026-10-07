"""Errores de dominio: el vocabulario compartido por las tres capas.

La Capa 3 los lanza, la Capa 2 decide y la Capa 1 los traduce a un cuerpo de
problem details. Aquí no se importa FastAPI: un error que conoce su propio
código HTTP invertiría la dependencia, y SPEC §3.1 exige lo contrario.

Cada error lleva sus metadatos de cable (`status`, `code`, `type_uri`, `title`)
como atributos de clase. Así la traducción de `app/api/exception_handlers.py` es
declarativa en vez de una escalera de `if/else`, y `tests/unit/test_errors.py`
fija esos valores contra la matriz de SPEC §7.2.

`detail` es por instancia: explica *esta* ocurrencia, mientras `title` se
mantiene genérico para que los clientes puedan comparar fallos por `title`
(SPEC §7.1).
"""

from typing import ClassVar


class ServiceError(Exception):
    """Clase base de todo fallo con representación en problem details.

    Attributes:
        status: Código de estado HTTP de la respuesta.
        code: Extensión estable y legible por máquina (RFC 9457 §3.2).
        type_uri: URI estable que identifica la clase de problema.
        title: Resumen corto y genérico de la clase de problema.
        default_detail: `detail` por instancia cuando quien lanza no da ninguno.
        headers: Cabeceras de respuesta adicionales que exige este error, si hay.
    """

    status: ClassVar[int]
    code: ClassVar[str]
    type_uri: ClassVar[str]
    title: ClassVar[str]
    default_detail: ClassVar[str]
    headers: ClassVar[dict[str, str] | None] = None

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail if detail is not None else self.default_detail
        super().__init__(self.detail)

    def __str__(self) -> str:
        return f"{type(self).__name__}: {self.detail}"


class UnauthorizedError(ServiceError):
    """Token Bearer ausente, vacío, mal formado o incorrecto. Los cuatro casos
    comparten un mismo `detail` a propósito: distinguirlos le daría a un atacante
    un oráculo para adivinar tokens (SPEC §4.2)."""

    status = 401
    code = "UNAUTHORIZED"
    type_uri = "/problems/unauthorized"
    title = "Unauthorized"
    default_detail = "Missing or invalid bearer token."
    headers = {"WWW-Authenticate": "Bearer"}


class ValidationError(ServiceError):
    """Petición estructuralmente inválida: JSON malformado, tipos equivocados, un
    campo requerido ausente, una clave desconocida de primer nivel, un
    `performed_at` sin offset, o un `skip`/`limit` fuera de rango."""

    status = 400
    code = "VALIDATION_ERROR"
    type_uri = "/problems/validation_error"
    title = "Request validation error"
    default_detail = "The request did not satisfy the API contract."


class NotFoundError(ServiceError):
    """Ninguna ruta coincide con el path de la petición."""

    status = 404
    code = "NOT_FOUND"
    type_uri = "/problems/not_found"
    title = "Resource not found"
    default_detail = "The requested resource does not exist."


class MethodNotAllowedError(ServiceError):
    """Verbo no soportado por la ruta. Es así como se rechazan `PUT` y `DELETE`
    sobre `/audit/logs`: un log de auditoría que se puede editar no es una
    auditoría (SPEC §6.2)."""

    status = 405
    code = "METHOD_NOT_ALLOWED"
    type_uri = "/problems/method_not_allowed"
    title = "Method not allowed"
    default_detail = "This resource is append-only; that verb does not exist."


class PayloadTooLargeError(ServiceError):
    """Se superó uno de tres límites distintos: el body de 1 MiB, el campo
    `details` de 64 KiB o el documento BSON de 16 MiB (SPEC §7.2)."""

    status = 413
    code = "PAYLOAD_TOO_LARGE"
    type_uri = "/problems/payload_too_large"
    title = "Payload too large"
    default_detail = "The payload exceeds the accepted size."


class UnsupportedMediaTypeError(ServiceError):
    """`Content-Type` distinto de `application/json` en una petición con cuerpo."""

    status = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    type_uri = "/problems/unsupported_media_type"
    title = "Unsupported media type"
    default_detail = "Content-Type must be application/json."


class InternalError(ServiceError):
    """Fallo no previsto. Siempre el último recurso: todo lo que llega aquí
    escapó a cualquier handler específico, y la causa pertenece al log, nunca a
    la respuesta (SPEC §7.1)."""

    status = 500
    code = "INTERNAL_ERROR"
    type_uri = "/problems/internal_error"
    title = "Internal server error"
    default_detail = "The service failed to handle the request."


class AuditStorageError(ServiceError):
    """MongoDB inalcanzable o con error. `503` y no `500` porque es
    infraestructura que quien llama puede reintentar; un `500` le quitaría esa
    opción (SPEC §6.4)."""

    status = 503
    code = "AUDIT_STORAGE_ERROR"
    type_uri = "/problems/audit_storage_error"
    title = "Audit storage unavailable"
    default_detail = "The audit storage is temporarily unavailable."
