"""Non-text Alembic revision declarations cannot establish trusted lineage."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_sqlite_lineage_16.py"


@pytest.mark.parametrize("column_type", ["INTEGER", "BLOB", "NUMERIC", "VARCHAR(64)"])
def test_noncanonical_stamp_type_is_diagnostic_and_fails_strict_gates(
    tmp_path: Path, column_type: str
) -> None:
    database = tmp_path / "science.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"CREATE TABLE alembic_version (version_num {column_type} NOT NULL PRIMARY KEY)"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('0038')")
        connection.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("INSERT INTO observations (note) VALUES ('private coral data')")
    original = database.read_bytes()
    for options, expected in [
        ([], 0),
        (["--fail-on-noncanonical-stamp"], 2),
        (["--fail-on-integrity-error"], 2),
    ]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(database), *options],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == expected, result.stderr
        report = json.loads(result.stdout)
        assert report["alembic_stamp_constraint_error"] == (
            "invalid_alembic_version_column_constraints"
        )
        assert report["classification"] == "requires_researcher_review"
        assert "private coral data" not in result.stdout
        assert database.read_bytes() == original


@pytest.mark.parametrize(
    ("declaration", "canonical"),
    [
        ("version_num TEXT NOT NULL PRIMARY KEY", True),
        ("version_num VARCHAR(32) NOT NULL PRIMARY KEY", True),
        ("version_num TEXT COLLATE BINARY NOT NULL PRIMARY KEY", True),
        ("version_num TEXT COLLATE NOCASE NOT NULL PRIMARY KEY", False),
        ("version_num TEXT COLLATE RTRIM NOT NULL PRIMARY KEY", False),
        ("version_num TEXT NOT NULL PRIMARY KEY DESC", False),
        ("version_num TEXT NOT NULL, PRIMARY KEY(version_num DESC)", False),
        ("version_num TEXT NOT NULL, PRIMARY KEY(version_num COLLATE NOCASE)", False),
        ("version_num TEXT NOT NULL, PRIMARY KEY(version_num ASC)", True),
    ],
)
def test_stamp_primary_key_semantics_in_both_comparison_inputs(
    tmp_path: Path, declaration: str, canonical: bool
) -> None:
    databases = [tmp_path / "source.sqlite", tmp_path / "copy.sqlite"]
    for database in databases:
        with sqlite3.connect(database) as connection:
            connection.execute(f"CREATE TABLE alembic_version ({declaration})")
            connection.execute("INSERT INTO alembic_version VALUES ('0038')")
            connection.execute("CREATE TABLE observations (note TEXT)")
            connection.execute("INSERT INTO observations VALUES ('private coral data')")
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    originals = [database.read_bytes() for database in databases]
    for options in [
        [],
        ["--fail-on-noncanonical-stamp"],
        ["--fail-on-integrity-error"],
        ["--fail-on-lineage-collision"],
    ]:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT), str(databases[0]),
                "--compare-to", str(databases[1]), *options,
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == (0 if canonical or not options else 2), result.stderr
        report = json.loads(result.stdout)
        expected = None if canonical else "invalid_alembic_version_column_constraints"
        assert report["alembic_stamp_constraint_error"] == expected
        assert report["classification"] == "requires_researcher_review"
        assert "private coral data" not in result.stdout
        assert [database.read_bytes() for database in databases] == originals
