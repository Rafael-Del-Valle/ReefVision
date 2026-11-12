"""Strict Alembic stamp acceptance must not silently pass missing or invalid metadata."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect_sqlite_lineage_16.py"


@pytest.mark.parametrize(
    ("schema", "revision", "expected_exit"),
    [
        ("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)", "0037", 0),
        (None, None, 2),
        ("CREATE TABLE alembic_version (version_num TEXT)", "0037", 2),
        ("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)", None, 2),
        ("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)", " 0037 ", 2),
    ],
)
def test_strict_stamp_gate_is_read_only_and_fail_closed(
    tmp_path: Path, schema: str | None, revision: str | None, expected_exit: int
) -> None:
    database = tmp_path / "research.sqlite"
    with sqlite3.connect(database) as connection:
        if schema is not None:
            connection.execute(schema)
            if revision is not None:
                connection.execute(
                    "INSERT INTO alembic_version(version_num) VALUES (?)", (revision,)
                )
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute(
            "INSERT INTO biological_sentinel VALUES ('private biological observation')"
        )
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(database), "--fail-on-noncanonical-stamp"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_exit, result.stderr
    report = json.loads(result.stdout)
    assert report["classification"] == "requires_researcher_review"
    assert report["read_only"] is True
    assert "private biological observation" not in result.stdout
    assert database.read_bytes() == before
