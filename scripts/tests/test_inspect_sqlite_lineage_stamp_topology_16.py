"""Regression: foreign Alembic stamp topology cannot pass lineage integrity acceptance."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect_sqlite_lineage_16.py"


@pytest.mark.parametrize(
    ("schema", "expected_error"),
    [
        ("CREATE TABLE alembic_version (version_num TEXT)", None),
        (
            "CREATE TABLE alembic_version (version_num TEXT, foreign_lineage TEXT)",
            "unexpected_alembic_version_columns",
        ),
        (
            "CREATE TABLE alembic_version (foreign_lineage TEXT, version_num TEXT)",
            "unexpected_alembic_version_columns",
        ),
    ],
)
def test_stamp_topology_gate_preserves_scientific_records(
    tmp_path: Path, schema: str, expected_error: str | None
) -> None:
    database = tmp_path / "research.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(schema)
        columns = [
            row[1] for row in connection.execute("PRAGMA table_info(alembic_version)")
        ]
        values = ["0037" if name == "version_num" else "preserve" for name in columns]
        placeholders = ", ".join("?" for _ in values)
        connection.execute(
            f"INSERT INTO alembic_version VALUES ({placeholders})", values
        )
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute(
            "INSERT INTO biological_sentinel VALUES ('private biological observation')"
        )
    before = database.read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fail-on-integrity-error",
            str(database),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (2 if expected_error else 0), result.stderr
    report = json.loads(result.stdout)
    assert report["alembic_stamp_validation_error"] == expected_error
    assert report["alembic_stamps"] == ["0037"]
    assert report["classification"] == "requires_researcher_review"
    assert "private biological observation" not in result.stdout
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT note FROM biological_sentinel"
        ).fetchone() == ("private biological observation",)
