"""Genera peticiones de prueba para la herramienta Vegeta."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

import httpx

OPERATIONS = ("POST", "LIST", "BYCHECKSUM")
DEFAULT_BASE_URL = "http://localhost:8083"
DEFAULT_OUT_DIR = Path("tests/stress/targets")
DEFAULT_COUNT = 1000
DEFAULT_READS = 200

LIST_QUERY = "skip=0&limit=50"
PERFORMED_AT_BASE = datetime(2024, 1, 1, tzinfo=UTC)


class LoadReport(NamedTuple):
    """Siembra: cuántos eventos se crearon (201) y cuántos eran replay (200)."""

    created: int
    existing: int


def generate_checksums(
    count: int, seed: int | None = None, *, salt: str = ""
) -> list[str]:
    """Devuelve ``count`` checksums únicos (sha256 de ``salt+seed:índice``).

    Args:
        count: Cantidad de elementos.
        seed: Semilla para generar los valores.
        salt: Texto que se añade a la semilla.

    Returns:
        La lista de checksums.
    """
    if count < 1:
        raise ValueError(f"count must be positive, got {count}")
    effective = seed if seed is not None else int.from_bytes(os.urandom(8), "big")
    return [
        hashlib.sha256(f"{salt}{effective}:{index}".encode()).hexdigest()
        for index in range(count)
    ]


def build_targets(
    operation: str, base_url: str, token: str, checksums: Sequence[str]
) -> str:
    """Compone los targets de Vegeta para una operación (una línea por target).

    Args:
        operation: Operación que se va a generar.
        base_url: Dirección base del servicio.
        token: Token de acceso.
        checksums: Lista de checksums.

    Returns:
        La lista de objetivos.
    """
    if operation not in OPERATIONS:
        raise ValueError(f"unknown operation: {operation}")
    root = base_url.rstrip("/")
    return "".join(
        _target_line(operation, root, token, index, checksum) + "\n"
        for index, checksum in enumerate(checksums)
    )


def _target_line(
    operation: str, root: str, token: str, index: int, checksum: str
) -> str:
    """Serializa una petición como un target JSON de Vegeta.

    Args:
        operation: Operación que se va a generar.
        root: Dirección base del servicio.
        token: Token de acceso.
        index: Posición del elemento.
        checksum: Valor que identifica el contenido.

    Returns:
        La línea del objetivo.
    """
    method = "POST" if operation == "POST" else "GET"
    body = _body(operation, index, checksum)
    headers: dict[str, list[str]] = {"Authorization": [f"Bearer {token}"]}
    target: dict = {
        "method": method,
        "url": _url(operation, root, checksum),
        "header": headers,
    }
    if body is not None:
        headers["Content-Type"] = ["application/json"]
        target["body"] = base64.b64encode(body.encode()).decode()
    return json.dumps(target, separators=(",", ":"))


def _url(operation: str, root: str, checksum: str) -> str:
    """Construye la URL de una operación.

    Args:
        operation: Operación que se va a generar.
        root: Dirección base del servicio.
        checksum: Valor que identifica el contenido.

    Returns:
        La URL construida.
    """
    if operation == "POST":
        return f"{root}/audit/logs"
    if operation == "LIST":
        return f"{root}/audit/logs?{LIST_QUERY}"
    return f"{root}/audit/logs/checksum/{quote(checksum, safe='')}"


def _body(operation: str, index: int, checksum: str) -> str | None:
    """Cuerpo del target, o ``None`` si el verbo no lleva.

    Args:
        operation: Operación que se va a generar.
        index: Posición del elemento.
        checksum: Valor que identifica el contenido.

    Returns:
        El cuerpo de la petición o None.
    """
    if operation == "POST":
        return _json(_event(index, checksum))
    return None


def _event(index: int, checksum: str) -> dict[str, object]:
    """Un evento de auditoría válido y único para el contrato de ``POST``.

    Args:
        index: Posición del elemento.
        checksum: Valor que identifica el contenido.

    Returns:
        El evento de prueba.
    """
    return {
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": checksum,
        "performed_at": _performed_at(index),
        "details": {"source": "vegeta", "index": index},
    }


def _performed_at(index: int) -> str:
    """RFC 3339 UTC con ``Z`` y milisegundos; único por índice.

    Args:
        index: Posición del elemento.

    Returns:
        La fecha del evento en formato RFC 3339.
    """
    moment = PERFORMED_AT_BASE + timedelta(seconds=index)
    return f"{moment:%Y-%m-%dT%H:%M:%S}.{moment.microsecond // 1000:03d}Z"


def _json(payload: dict) -> str:
    """Convierte una carga útil en texto JSON.

    Args:
        payload: Datos que se van a enviar.

    Returns:
        El texto JSON.
    """
    return json.dumps(payload, separators=(",", ":"))


def _auth(token: str) -> dict[str, str]:
    """Crea las cabeceras de autorización.

    Args:
        token: Token de acceso.

    Returns:
        Las cabeceras de autenticación.
    """
    return {"Authorization": f"Bearer {token}"}


def write_targets(
    out_dir: Path,
    base_url: str,
    token: str,
    post_checksums: Sequence[str],
    read_checksums: Sequence[str],
) -> dict[str, Path]:
    """Escribe un fichero por operación y devuelve ``{operación: ruta}``.

    Args:
        out_dir: Carpeta donde se escriben los archivos.
        base_url: Dirección base del servicio.
        token: Token de acceso.
        post_checksums: Checksums para las peticiones POST.
        read_checksums: Checksums para las peticiones de lectura.

    Returns:
        Las rutas de los archivos escritos.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for operation in OPERATIONS:
        checksums = read_checksums if operation == "BYCHECKSUM" else post_checksums
        path = out_dir / f"{operation.lower()}.txt"
        path.write_text(
            build_targets(operation, base_url, token, checksums), encoding="utf-8"
        )
        written[operation.lower()] = path
    return written


@contextmanager
def _http(client: httpx.Client | None) -> Iterator[httpx.Client]:
    """Entrega el cliente dado, o crea y cierra uno propio.

    Args:
        client: Cliente que usa la prueba.

    Returns:
        No retorna valor.
    """
    if client is not None:
        yield client
    else:
        with httpx.Client(timeout=10.0) as owned:
            yield owned


def load_documents(
    base_url: str,
    token: str,
    checksums: Sequence[str],
    *,
    client: httpx.Client | None = None,
) -> LoadReport:
    """Siembra los eventos del set de lectura con ``POST /audit/logs``.

    Args:
        base_url: Dirección base del servicio.
        token: Token de acceso.
        checksums: Lista de checksums.
        client: Cliente que usa la prueba.

    Returns:
        El resumen de eventos creados y repetidos.
    """
    root = base_url.rstrip("/")
    created = existing = 0
    with _http(client) as http:
        for index, checksum in enumerate(checksums):
            response = http.post(
                f"{root}/audit/logs",
                json=_event(index, checksum),
                headers=_auth(token),
            )
            if response.status_code == 201:
                created += 1
            elif response.status_code == 200:
                existing += 1
            else:
                response.raise_for_status()
    return LoadReport(created=created, existing=existing)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: siembra opcional y escribe los tres ficheros de targets.

    Args:
        argv: Argumentos de la línea de comandos.

    Returns:
        El código de salida.
    """
    args = _parse_args(argv)

    token = os.environ.get("SERVICE_API_TOKEN", "").strip()
    if not token:
        print(
            "error: SERVICE_API_TOKEN is required; every target carries a "
            "Bearer header and without it Vegeta would only collect 401s.",
            file=sys.stderr,
        )
        return 2

    try:
        post_checksums = generate_checksums(args.count, args.seed, salt="post")
        read_checksums = generate_checksums(args.reads, args.seed, salt="read")
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.load:
        report = load_documents(args.base_url, token, read_checksums)
        print(f"seed: {report.created} created, {report.existing} already present")

    for operation, path in write_targets(
        args.out_dir, args.base_url, token, post_checksums, read_checksums
    ).items():
        print(f"{operation}: {path}")

    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Lee los argumentos de la línea de comandos.

    Args:
        argv: Argumentos de la línea de comandos.

    Returns:
        Los argumentos leídos.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument(
        "--reads",
        type=int,
        default=DEFAULT_READS,
        help="Checksums del set de lectura para los GET por checksum.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--load",
        action="store_true",
        help="Sembrar el set de lectura con POST antes de escribir los targets.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
