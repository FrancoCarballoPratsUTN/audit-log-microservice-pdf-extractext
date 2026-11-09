"""Pruebas del generador de peticiones de carga."""

from __future__ import annotations

import base64
import json
import re
from unittest.mock import Mock

import httpx
import pytest

from tests.stress.scripts.gen_targets import (
    build_targets,
    generate_checksums,
    load_documents,
    main,
    write_targets,
)

BASE_URL = "http://stress.test:8083"
TOKEN = "tok-abc123"
RFC3339_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def targets_of(targets: str) -> list[dict]:
    """Decodifica el fichero de targets: una línea es una petición.

    Args:
        targets: Lista de objetivos.

    Returns:
        La lista de objetivos leídos.
    """
    return [json.loads(line) for line in targets.splitlines()]


def body_of(target: dict) -> dict:
    """Decodifica el cuerpo base64 de un target.

    Args:
        target: Objetivo de la prueba.

    Returns:
        El cuerpo decodificado.
    """
    return json.loads(base64.b64decode(target["body"]))


def fake_client(*statuses: int) -> Mock:
    """Cliente httpx falso: responde un estado por llamada, en orden.

    Args:
        *statuses: Argumentos adicionales.

    Returns:
        El cliente falso.
    """

    def responses() -> list[Mock]:
        """Devuelve las respuestas simuladas."""
        return [Mock(status_code=status) for status in statuses]

    client = Mock()
    client.post.side_effect = responses()
    return client


def test_checksums_are_unique_and_reproducible():
    """Comprueba que los checksums son únicos y reproducibles."""
    first = generate_checksums(1000, seed=42)

    assert first == generate_checksums(1000, seed=42)
    assert first != generate_checksums(1000, seed=43)
    assert len(set(first)) == 1000
    assert all(len(checksum) == 64 for checksum in first)


def test_checksums_reject_a_non_positive_count():
    """Comprueba que un número de checksums no positivo se rechaza."""
    with pytest.raises(ValueError, match="count"):
        generate_checksums(0)


def test_the_post_and_read_salts_produce_disjoint_sets():
    """Comprueba que las sales de escritura y lectura no coinciden."""
    posted = set(generate_checksums(100, 7, salt="post"))
    read = set(generate_checksums(100, 7, salt="read"))

    assert posted.isdisjoint(read)


def test_post_target_is_a_base64_json_line():
    """Comprueba que el objetivo POST es una línea JSON en base64."""
    (target,) = targets_of(build_targets("POST", BASE_URL, TOKEN, ["abc123"]))

    assert target["method"] == "POST"
    assert target["url"] == f"{BASE_URL}/audit/logs"
    assert target["header"]["Authorization"] == [f"Bearer {TOKEN}"]
    assert target["header"]["Content-Type"] == ["application/json"]
    body = body_of(target)
    assert body["action"] == "pdf.extract"
    assert body["entity_type"] == "document"
    assert body["checksum"] == "abc123"
    assert RFC3339_Z.match(body["performed_at"])


def test_post_targets_carry_distinct_performed_at():
    """Comprueba que cada objetivo POST lleva una fecha distinta."""
    first, second = targets_of(build_targets("POST", BASE_URL, TOKEN, ["a", "b"]))

    assert body_of(first)["performed_at"] != body_of(second)["performed_at"]


def test_list_target_uses_the_global_list_url_without_a_body():
    """Comprueba que el objetivo de listado usa la URL global y no lleva cuerpo."""
    targets = targets_of(build_targets("LIST", BASE_URL, TOKEN, ["a", "b"]))

    assert len(targets) == 2
    assert all(target["method"] == "GET" for target in targets)
    assert all(
        target["url"] == f"{BASE_URL}/audit/logs?skip=0&limit=50" for target in targets
    )
    assert all(
        target["header"] == {"Authorization": [f"Bearer {TOKEN}"]} for target in targets
    )
    assert all("body" not in target for target in targets)


def test_bychecksum_target_uses_the_checksum_path():
    """Comprueba que el objetivo por checksum usa la ruta correcta."""
    (target,) = targets_of(build_targets("BYCHECKSUM", BASE_URL, TOKEN, ["abc123"]))

    assert target["method"] == "GET"
    assert target["url"] == f"{BASE_URL}/audit/logs/checksum/abc123"
    assert target["header"] == {"Authorization": [f"Bearer {TOKEN}"]}
    assert "body" not in target


def test_an_unknown_operation_is_rejected():
    """Comprueba que una operación desconocida se rechaza."""
    with pytest.raises(ValueError, match="PATCH"):
        build_targets("PATCH", BASE_URL, TOKEN, ["abc123"])


def test_write_targets_writes_one_file_per_operation(tmp_path):
    """Comprueba que se escribe un archivo por operación.

    Args:
        tmp_path: Ruta temporal para archivos de prueba.

    Returns:
        No retorna valor.
    """
    written = write_targets(
        tmp_path,
        BASE_URL,
        TOKEN,
        generate_checksums(3, seed=7, salt="post"),
        generate_checksums(2, seed=7, salt="read"),
    )

    assert set(written) == {"post", "list", "bychecksum"}
    assert len(targets_of(written["post"].read_text(encoding="utf-8"))) == 3
    assert len(targets_of(written["list"].read_text(encoding="utf-8"))) == 3
    assert len(targets_of(written["bychecksum"].read_text(encoding="utf-8"))) == 2
    assert all(
        target["method"] == "POST"
        for target in targets_of(written["post"].read_text(encoding="utf-8"))
    )


def test_load_documents_counts_created_and_replayed():
    """Comprueba que se cuentan los eventos creados y repetidos."""
    client = fake_client(201, 200)

    report = load_documents(BASE_URL, TOKEN, ["abc123", "def456"], client=client)

    assert (report.created, report.existing) == (1, 1)


def test_load_documents_propagates_an_unexpected_status():
    """Comprueba que un estado inesperado se propaga."""
    client = Mock()
    client.post.return_value = Mock(
        status_code=401,
        raise_for_status=Mock(
            side_effect=httpx.HTTPStatusError("401", request=Mock(), response=Mock())
        ),
    )

    with pytest.raises(httpx.HTTPStatusError):
        load_documents(BASE_URL, TOKEN, ["abc123"], client=client)


def test_cli_needs_the_token_and_writes_nothing(monkeypatch, tmp_path, capsys):
    """Comprueba que la herramienta exige el token y no escribe archivos.

    Args:
        monkeypatch: Utilidad de pytest para sustituir valores.
        tmp_path: Ruta temporal para archivos de prueba.
        capsys: Capturador de la salida de pytest.

    Returns:
        No retorna valor.
    """
    monkeypatch.delenv("SERVICE_API_TOKEN", raising=False)

    exit_code = main(["--count", "2", "--out-dir", str(tmp_path)])

    assert exit_code == 2
    assert "SERVICE_API_TOKEN" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_cli_writes_the_three_files_with_a_token(monkeypatch, tmp_path):
    """Comprueba que la herramienta escribe los tres archivos con token.

    Args:
        monkeypatch: Utilidad de pytest para sustituir valores.
        tmp_path: Ruta temporal para archivos de prueba.

    Returns:
        No retorna valor.
    """
    monkeypatch.setenv("SERVICE_API_TOKEN", TOKEN)

    exit_code = main(["--count", "5", "--seed", "42", "--out-dir", str(tmp_path)])

    assert exit_code == 0
    assert {path.name for path in tmp_path.iterdir()} == {
        "post.txt",
        "list.txt",
        "bychecksum.txt",
    }
