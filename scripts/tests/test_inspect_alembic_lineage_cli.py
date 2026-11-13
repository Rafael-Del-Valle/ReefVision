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
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for table in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
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


@pytest.mark.parametrize(
    "version_schema",
    [
        "CREATE TABLE alembic_version (revision TEXT)",
        "CREATE VIEW alembic_version AS SELECT '0038' AS version_num",
    ],
)
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


@pytest.mark.parametrize(
    ("suffix", "expected_warning"),
    [
        ("-wal", "wal_sidecar_requires_consistent_snapshot"),
        ("-shm", "shared_memory_sidecar_requires_consistent_snapshot"),
    ],
)
def test_strict_preflight_detects_sidecars_through_symlink_without_mutation(
    tmp_path: Path, suffix: str, expected_warning: str
) -> None:
    database = tmp_path / "original.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('0037')")
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES ('preserve')")
    sidecar = Path(str(database) + suffix)
    sidecar.write_bytes(b"snapshot-sidecar-sentinel")
    alias = tmp_path / "alias.sqlite"
    try:
        alias.symlink_to(database)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem does not support symlinks")
    before_database = database.read_bytes()
    before_sidecar = sidecar.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(alias)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert expected_warning in report["warnings"]
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before_database
    assert sidecar.read_bytes() == before_sidecar


def test_sqlite_integrity_preflight_reports_clean_database(tmp_path: Path) -> None:
    database = tmp_path / "clean.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0037')")
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["sqlite_integrity_ok"] is True
    assert report["sqlite_full_integrity_ok"] is True
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before


def test_full_integrity_preflight_preserves_indexed_research_data(tmp_path: Path) -> None:
    database = tmp_path / "indexed.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0037')")
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE biological_sentinel (id INTEGER PRIMARY KEY, note TEXT UNIQUE)"
        )
        connection.execute("INSERT INTO biological_sentinel VALUES (1, 'preserve')")
        connection.execute("CREATE INDEX sentinel_note_idx ON biological_sentinel(note)")
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["sqlite_integrity_ok"] is True
    assert report["sqlite_full_integrity_ok"] is True
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
            "preserve",
        )


def test_corrupt_sqlite_file_fails_closed_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.sqlite"
    database.write_bytes(b"not a SQLite database; preserve this evidence")
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert database.read_bytes() == before


def test_orphaned_foreign_key_blocks_strict_preflight_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "orphaned.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('0037')")
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE observations (id INTEGER PRIMARY KEY, "
            "parent_id INTEGER REFERENCES parents(id), note TEXT)"
        )
        # SQLite permits legacy orphaned records when foreign_keys is disabled.
        connection.execute("INSERT INTO observations VALUES (1, 999, 'preserve')")
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["sqlite_integrity_ok"] is True
    assert report["sqlite_foreign_key_violations"] == 1
    assert "sqlite_foreign_key_violations" in report["warnings"]
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT note FROM observations").fetchone() == ("preserve",)


def test_valid_foreign_keys_allow_warning_free_preflight(tmp_path: Path) -> None:
    database = tmp_path / "linked.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0037')")
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE observations (id INTEGER PRIMARY KEY, "
            "parent_id INTEGER REFERENCES parents(id))"
        )
        connection.execute("INSERT INTO parents VALUES (1)")
        connection.execute("INSERT INTO observations VALUES (1, 1)")
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["sqlite_foreign_key_violations"] == 0
    assert report["warnings"] == []
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before


@pytest.mark.parametrize("strict", [False, True])
def test_malformed_foreign_key_schema_is_structured_and_read_only(
    tmp_path: Path, strict: bool
) -> None:
    database = tmp_path / "invalid-fk.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('0037')")
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE parents (id INTEGER)")
        connection.execute(
            "CREATE TABLE observations (parent_id INTEGER REFERENCES parents(id), note TEXT)"
        )
        connection.execute("INSERT INTO observations VALUES (999, 'preserve')")
    before = database.read_bytes()
    command = [sys.executable, str(SCRIPT)]
    if strict:
        command.append("--fail-on-warning")
    result = subprocess.run([*command, str(database)], capture_output=True, text=True, check=False)
    assert result.returncode == (2 if strict else 0), result.stderr
    report = json.loads(result.stdout)
    assert report["sqlite_foreign_key_violations"] is None
    assert "foreign key mismatch" in report["sqlite_foreign_key_check_error"]
    assert "sqlite_foreign_key_check_failed" in report["warnings"]
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT note FROM observations").fetchone() == ("preserve",)


@pytest.mark.parametrize("strict", [False, True])
def test_foreign_alembic_version_column_is_reported_without_mutation(
    tmp_path: Path, strict: bool
) -> None:
    database = tmp_path / "foreign-stamp.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num TEXT NOT NULL, foreign_lineage TEXT)"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('0037', 'preserve')")
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
    before = database.read_bytes()
    command = [sys.executable, str(SCRIPT)]
    if strict:
        command.append("--fail-on-warning")
    result = subprocess.run([*command, str(database)], capture_output=True, text=True, check=False)
    assert result.returncode == (2 if strict else 0), result.stderr
    report = json.loads(result.stdout)
    assert "unexpected_alembic_version_columns" in report["warnings"]
    assert report["revision_rows"] == ["0037"]
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before


@pytest.mark.parametrize(
    "revision",
    [" 0037", "0037 ", "0037\n", "0037\x00", "0037\x7f", "\t"],
)
@pytest.mark.parametrize("strict", [False, True])
def test_noncanonical_revision_marker_fails_closed_without_mutation(
    tmp_path: Path, revision: str, strict: bool
) -> None:
    database = tmp_path / "noncanonical-revision.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES ('preserve')")
    before = database.read_bytes()
    command = [sys.executable, str(SCRIPT)]
    if strict:
        command.append("--fail-on-warning")
    result = subprocess.run([*command, str(database)], capture_output=True, text=True, check=False)
    assert result.returncode == (2 if strict else 0), result.stderr
    report = json.loads(result.stdout)
    assert "invalid_revision_marker_count_or_value" in report["warnings"]
    assert report["revision_rows"] == [revision]
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
            "preserve",
        )


@pytest.mark.parametrize("revisions", [[], ["0037", "0037"], ["0037", "0038"]])
@pytest.mark.parametrize("strict", [False, True])
def test_invalid_revision_row_cardinality_fails_closed_without_mutation(
    tmp_path: Path, revisions: list[str], strict: bool
) -> None:
    database = tmp_path / "invalid-revision-rows.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO alembic_version VALUES (?)", [(value,) for value in revisions]
        )
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES ('preserve')")
    before = database.read_bytes()
    command = [sys.executable, str(SCRIPT)]
    if strict:
        command.append("--fail-on-warning")
    result = subprocess.run([*command, str(database)], capture_output=True, text=True, check=False)
    assert result.returncode == (2 if strict else 0), result.stderr
    report = json.loads(result.stdout)
    assert "invalid_revision_marker_count_or_value" in report["warnings"]
    assert report["revision_rows"] == revisions
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
            "preserve",
        )


@pytest.mark.parametrize("revision", [None, 38, b"\x00\xff0038"])
@pytest.mark.parametrize("strict", [False, True])
def test_nontext_revision_markers_are_json_safe_and_read_only(
    tmp_path: Path, revision: object, strict: bool
) -> None:
    database = tmp_path / "nontext-revision.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES ('preserve')")
    before = database.read_bytes()
    command = [sys.executable, str(SCRIPT)]
    if strict:
        command.append("--fail-on-warning")
    result = subprocess.run([*command, str(database)], capture_output=True, text=True, check=False)
    assert result.returncode == (2 if strict else 0), result.stderr
    report = json.loads(result.stdout)
    assert "invalid_revision_marker_count_or_value" in report["warnings"]
    assert report["revision_rows"] == [None]
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
            "preserve",
        )
