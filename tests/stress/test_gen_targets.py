"""Tests de :mod:`tests.stress.scripts.gen_targets`.

Cubre la lógica pura (unicidad de checksums, serialización de targets,
escritura de ficheros) y el único efecto HTTP de la preparación (la siembra del
set de lectura, con un cliente mock). El stress real lo hacen k6 y vegeta, no
pytest: aquí sólo se garantiza que los targets que Vegeta atacará tienen la
forma que el contrato de AUDA exige.
"""

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
    """Decodifica el fichero de targets: una línea es una petición."""
    return [json.loads(line) for line in targets.splitlines()]


def body_of(target: dict) -> dict:
    """Decodifica el cuerpo base64 de un target."""
    return json.loads(base64.b64decode(target["body"]))


def fake_client(*statuses: int) -> Mock:
    """Cliente httpx falso: responde un estado por llamada, en orden."""

    def responses() -> list[Mock]:
        return [Mock(status_code=status) for status in statuses]

    client = Mock()
    client.post.side_effect = responses()
    return client


def test_checksums_are_unique_and_reproducible():
    first = generate_checksums(1000, seed=42)

    assert first == generate_checksums(1000, seed=42)
    assert first != generate_checksums(1000, seed=43)
    assert len(set(first)) == 1000
    assert all(len(checksum) == 64 for checksum in first)


def test_checksums_reject_a_non_positive_count():
    with pytest.raises(ValueError, match="count"):
        generate_checksums(0)


def test_the_post_and_read_salts_produce_disjoint_sets():
    posted = set(generate_checksums(100, 7, salt="post"))
    read = set(generate_checksums(100, 7, salt="read"))

    assert posted.isdisjoint(read)


def test_post_target_is_a_base64_json_line():
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
    first, second = targets_of(build_targets("POST", BASE_URL, TOKEN, ["a", "b"]))

    assert body_of(first)["performed_at"] != body_of(second)["performed_at"]


def test_list_target_uses_the_global_list_url_without_a_body():
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
    (target,) = targets_of(build_targets("BYCHECKSUM", BASE_URL, TOKEN, ["abc123"]))

    assert target["method"] == "GET"
    assert target["url"] == f"{BASE_URL}/audit/logs/checksum/abc123"
    assert target["header"] == {"Authorization": [f"Bearer {TOKEN}"]}
    assert "body" not in target


def test_an_unknown_operation_is_rejected():
    with pytest.raises(ValueError, match="PATCH"):
        build_targets("PATCH", BASE_URL, TOKEN, ["abc123"])


def test_write_targets_writes_one_file_per_operation(tmp_path):
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
    client = fake_client(201, 200)

    report = load_documents(BASE_URL, TOKEN, ["abc123", "def456"], client=client)

    assert (report.created, report.existing) == (1, 1)


def test_load_documents_propagates_an_unexpected_status():
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
    monkeypatch.delenv("SERVICE_API_TOKEN", raising=False)

    exit_code = main(["--count", "2", "--out-dir", str(tmp_path)])

    assert exit_code == 2
    assert "SERVICE_API_TOKEN" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_cli_writes_the_three_files_with_a_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SERVICE_API_TOKEN", TOKEN)

    exit_code = main(["--count", "5", "--seed", "42", "--out-dir", str(tmp_path)])

    assert exit_code == 0
    assert {path.name for path in tmp_path.iterdir()} == {
        "post.txt",
        "list.txt",
        "bychecksum.txt",
    }
