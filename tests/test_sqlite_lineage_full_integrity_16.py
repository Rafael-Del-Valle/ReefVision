"""Full SQLite integrity evidence for the read-only 1.6 lineage acceptance gate."""
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_sqlite_lineage_16.py"


def test_full_integrity_evidence_and_read_only_acceptance(tmp_path: Path) -> None:
    database = tmp_path / "observations.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('0041')")
        connection.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY, species TEXT)")
        connection.execute("INSERT INTO observations VALUES (1, 'sensitive coral')")
    original = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(database), "--fail-on-integrity-error"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["quick_check_details"] == ["ok"]
    assert evidence["integrity_check_details"] == ["ok"]
    assert evidence["classification"] == "requires_researcher_review"
    assert "sensitive coral" not in result.stdout
    assert database.read_bytes() == original


def test_comparison_reports_both_full_integrity_checks(tmp_path: Path) -> None:
    databases = [tmp_path / "primary.sqlite", tmp_path / "reference.sqlite"]
    for database in databases:
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
            connection.execute("INSERT INTO alembic_version VALUES ('0041')")
    originals = [database.read_bytes() for database in databases]
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), str(databases[0]),
            "--compare-to", str(databases[1]),
            "--fail-on-integrity-error",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["integrity_check_details"] == ["ok"]
    assert evidence["schema_comparison"]["reference_integrity"]["integrity_check_details"] == ["ok"]
    assert evidence["alembic_stamps"] == ["0041"]
    assert evidence["schema_comparison"]["reference_alembic_stamps"] == ["0041"]
    assert [database.read_bytes() for database in databases] == originals


def test_comparison_exposes_distinct_reference_revision_without_observation_data(tmp_path: Path) -> None:
    primary = tmp_path / "primary.sqlite"
    reference = tmp_path / "reference.sqlite"
    for database, revision in ((primary, "0041"), (reference, "0042")):
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
            connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
            connection.execute("CREATE TABLE observations (species TEXT)")
            connection.execute("INSERT INTO observations VALUES ('private coral observation')")
    originals = (primary.read_bytes(), reference.read_bytes())
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(primary), "--compare-to", str(reference),
         "--fail-on-revision-mismatch"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["alembic_stamps"] == ["0041"]
    assert evidence["schema_comparison"]["reference_alembic_stamps"] == ["0042"]
    assert evidence["schema_comparison"]["revision_markers_match"] is False
    assert evidence["schema_comparison"]["requires_researcher_review"] is True
    assert "private coral observation" not in result.stdout
    assert (primary.read_bytes(), reference.read_bytes()) == originals
