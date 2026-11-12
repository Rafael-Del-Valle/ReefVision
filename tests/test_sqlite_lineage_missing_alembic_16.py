"""Regression: missing Alembic lineage cannot pass the optional integrity gate."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_sqlite_lineage_16.py"


def _run(*paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *paths],
        check=False,
        capture_output=True,
        text=True,
    )


def test_unstamped_database_fails_integrity_gate_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "unstamped.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("INSERT INTO scientific_records (note) VALUES (?)", ("private observation",))
    original = database.read_bytes()
    informational = _run(str(database))
    assert informational.returncode == 0, informational.stderr
    report = json.loads(informational.stdout)
    assert report["alembic_stamp_validation_error"] == "missing_alembic_version_table"
    assert report["classification"] == "requires_researcher_review"
    assert "private observation" not in informational.stdout

    gated = _run(str(database), "--fail-on-integrity-error")
    assert gated.returncode == 2, gated.stderr
    assert json.loads(gated.stdout)["alembic_stamp_validation_error"] == (
        "missing_alembic_version_table"
    )
    assert database.read_bytes() == original


def test_unstamped_reference_fails_integrity_gate_without_mutation(tmp_path: Path) -> None:
    current = tmp_path / "current.sqlite"
    reference = tmp_path / "reference.sqlite"
    for database in (current, reference):
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
            connection.execute("INSERT INTO alembic_version VALUES ('0038')")
    with sqlite3.connect(reference) as connection:
        connection.execute("DROP TABLE alembic_version")
    originals = [database.read_bytes() for database in (current, reference)]
    result = _run(
        str(current), "--compare-to", str(reference), "--fail-on-integrity-error"
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_comparison"]["reference_integrity"][
        "alembic_stamp_validation_error"
    ] == "missing_alembic_version_table"
    assert report["schema_comparison"]["requires_researcher_review"] is True
    assert [database.read_bytes() for database in (current, reference)] == originals
