"""CLI preflight regressions for the read-only Alembic lineage inspector."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect-alembic-lineage.py"


@pytest.mark.parametrize(
    ("revision", "strict", "expected_status"),
    [
        ("0038", True, 2),
        ("0038", False, 0),
        ("0037", True, 0),
        ("0037", False, 0),
    ],
)
def test_cli_strict_mode_is_opt_in_and_never_mutates_database(
    tmp_path: Path, revision: str, strict: bool, expected_status: int
) -> None:
    database = tmp_path / "research.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for table in ("scientific_records", "environmental_cache_entries", "computed_metric_definitions", "computed_metric_results"):
            connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE biological_sentinel (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES (1, 'preserve')")
    # This synthetic fixture has no 1.6 schema-family tables. Its revision 0038
    # marker is ambiguous and must never be treated as upgrade authorization.
    before = database.read_bytes()
    command = [sys.executable, str(SCRIPT)]
    if strict:
        command.append("--fail-on-warning")
    completed = subprocess.run(
        [*command, str(database)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == expected_status, completed.stderr
    report = json.loads(completed.stdout)
    assert report["upgrade_authorized"] is False
    assert ("revision_0038_requires_schema_lineage_reconciliation" in report["warnings"]) == (
        revision == "0038"
    )
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
            "preserve",
        )


def test_strict_cli_missing_database_does_not_create_it(tmp_path: Path) -> None:
    database = tmp_path / "missing.sqlite"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert not database.exists()


@pytest.mark.parametrize("version_schema", ["CREATE TABLE alembic_version (revision TEXT)", "CREATE VIEW alembic_version AS SELECT '0038' AS version_num"])
def test_malformed_revision_storage_fails_closed_without_mutation(
    tmp_path: Path, version_schema: str
) -> None:
    database = tmp_path / "malformed.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(version_schema)
        connection.execute("CREATE TABLE biological_sentinel (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES (1, 'preserve')")
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["upgrade_authorized"] is False
    expected = (
        "missing_alembic_version_column"
        if version_schema.startswith("CREATE TABLE")
        else "missing_alembic_version_table"
    )
    assert expected in report["warnings"]
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
            "preserve",
        )
