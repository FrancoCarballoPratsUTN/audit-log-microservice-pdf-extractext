"""Define los errores del servicio y sus datos."""

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
        """Crea un error con un detalle opcional.

        Args:
            detail: Detalle del error.

        Returns:
            No retorna valor.
        """
        self.detail = detail if detail is not None else self.default_detail
        super().__init__(self.detail)

    def __str__(self) -> str:
        """Devuelve el nombre del error y su detalle."""
        return f"{type(self).__name__}: {self.detail}"


class UnauthorizedError(ServiceError):
    """Token Bearer ausente, vacío, mal formado o incorrecto. Los cuatro casos
    comparten un mismo `detail` a propósito: distinguirlos le daría a un atacante
    un oráculo para adivinar tokens (SPEC §4.2)."""

    status, code, type_uri, title, default_detail = (
        401,
        "UNAUTHORIZED",
        "/problems/unauthorized",
        "Unauthorized",
        "Missing or invalid bearer token.",
    )
    headers = {"WWW-Authenticate": "Bearer"}


class ValidationError(ServiceError):
    """Petición estructuralmente inválida: JSON malformado, tipos equivocados,
    un campo requerido ausente, una clave desconocida de primer nivel, un
    `performed_at` sin offset, o un `skip`/`limit` fuera de rango."""

    status, code, type_uri, title, default_detail = (
        400,
        "VALIDATION_ERROR",
        "/problems/validation_error",
        "Request validation error",
        "The request did not satisfy the API contract.",
    )


class NotFoundError(ServiceError):
    """Ninguna ruta coincide con el path de la petición."""

    status, code, type_uri, title, default_detail = (
        404,
        "NOT_FOUND",
        "/problems/not_found",
        "Resource not found",
        "The requested resource does not exist.",
    )


class MethodNotAllowedError(ServiceError):
    """Verbo no soportado por la ruta. Es así como se rechazan `PUT` y `DELETE`
    sobre `/audit/logs`: un log de auditoría que se puede editar no es una
    auditoría (SPEC §6.2)."""

    status, code, type_uri, title, default_detail = (
        405,
        "METHOD_NOT_ALLOWED",
        "/problems/method_not_allowed",
        "Method not allowed",
        "This resource is append-only; that verb does not exist.",
    )


class PayloadTooLargeError(ServiceError):
    """Se superó uno de tres límites distintos: el body de 1 MiB, el campo
    `details` de 64 KiB o el documento BSON de 16 MiB (SPEC §7.2)."""

    status, code, type_uri, title, default_detail = (
        413,
        "PAYLOAD_TOO_LARGE",
        "/problems/payload_too_large",
        "Payload too large",
        "The payload exceeds the accepted size.",
    )


class UnsupportedMediaTypeError(ServiceError):
    """`Content-Type` distinto de `application/json` en una petición con cuerpo."""

    status, code, type_uri, title, default_detail = (
        415,
        "UNSUPPORTED_MEDIA_TYPE",
        "/problems/unsupported_media_type",
        "Unsupported media type",
        "Content-Type must be application/json.",
    )


class InternalError(ServiceError):
    """Fallo no previsto. Siempre el último recurso: todo lo que llega aquí
    escapó a cualquier handler específico, y la causa pertenece al log, nunca a
    la respuesta (SPEC §7.1)."""

    status, code, type_uri, title, default_detail = (
        500,
        "INTERNAL_ERROR",
        "/problems/internal_error",
        "Internal server error",
        "The service failed to handle the request.",
    )


class AuditStorageError(ServiceError):
    """MongoDB inalcanzable o con error. `503` y no `500` porque es
    infraestructura que quien llama puede reintentar; un `500` le quitaría esa
    opción (SPEC §6.4)."""

    status, code, type_uri, title, default_detail = (
        503,
        "AUDIT_STORAGE_ERROR",
        "/problems/audit_storage_error",
        "Audit storage unavailable",
        "The audit storage is temporarily unavailable.",
    )
