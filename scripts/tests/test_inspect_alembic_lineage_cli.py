"""CLI preflight regressions for the read-only Alembic lineage inspector."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect-alembic-lineage.py"


def _create_0039_metric_pair(connection: sqlite3.Connection, variant: str = "valid") -> None:
    """Mirror the independent 1.1 scalar metric migration's SQLite contract."""
    definition_sql = (
        "CREATE TABLE computed_metric_definitions ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "name VARCHAR(200) NOT NULL, expression VARCHAR(1000) NOT NULL, "
        "formula_version VARCHAR(100) NOT NULL, input_spec_json JSON NOT NULL, "
        "output_unit VARCHAR(50) NOT NULL, definition_sha256 VARCHAR(64) NOT NULL, "
        "created_at DATETIME NOT NULL)"
    )
    result_sql = (
        "CREATE TABLE computed_metric_results ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "definition_id VARCHAR(36) NOT NULL "
        "REFERENCES computed_metric_definitions(id) ON DELETE RESTRICT, "
        "observed_at DATETIME NOT NULL, payload_json JSON NOT NULL, "
        "content_sha256 VARCHAR(64) NOT NULL, "
        "workflow_run_id VARCHAR(36) REFERENCES workflow_runs(id) ON DELETE RESTRICT, "
        "workflow_node_run_id VARCHAR(36) REFERENCES workflow_node_runs(id) ON DELETE RESTRICT, "
        "created_at DATETIME NOT NULL, "
        "CONSTRAINT uq_computed_metric_result_workflow_node_run UNIQUE (workflow_node_run_id))"
    )
    if variant == "unit_type":
        definition_sql = definition_sql.replace("output_unit VARCHAR(50)", "output_unit TEXT")
    if variant == "formula_nullable":
        definition_sql = definition_sql.replace(
            "formula_version VARCHAR(100) NOT NULL", "formula_version VARCHAR(100)"
        )
    if variant == "workflow_cascade":
        result_sql = result_sql.replace(
            "REFERENCES workflow_runs(id) ON DELETE RESTRICT",
            "REFERENCES workflow_runs(id) ON DELETE CASCADE",
        )
    if variant == "missing_unique":
        result_sql = result_sql.replace(
            ", CONSTRAINT uq_computed_metric_result_workflow_node_run "
            "UNIQUE (workflow_node_run_id)",
            "",
        )
    if variant == "unique_renamed":
        result_sql = result_sql.replace(
            "uq_computed_metric_result_workflow_node_run", "renamed_metric_result"
        )
    if variant == "unique_unnamed":
        result_sql = result_sql.replace(
            "CONSTRAINT uq_computed_metric_result_workflow_node_run ", ""
        )
    if variant == "duplicate_workflow_fk":
        result_sql = result_sql[:-1] + (
            ", FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id) ON DELETE RESTRICT)"
        )
    connection.execute(definition_sql)
    connection.execute(result_sql)
    connection.execute(
        "CREATE INDEX ix_computed_metric_definition_project "
        "ON computed_metric_definitions (project_id, created_at)"
    )
    if variant != "missing_index":
        connection.execute(
            "CREATE INDEX ix_computed_metric_result_project "
            "ON computed_metric_results (project_id, created_at)"
        )
    if variant == "result_trigger":
        connection.execute(
            "CREATE TRIGGER rewrite_metric AFTER INSERT ON computed_metric_results "
            "BEGIN UPDATE computed_metric_results SET payload_json = 'PRIVATE_TRIGGER_BODY' "
            "WHERE id = NEW.id; END"
        )


def _add_0041_aggregate_columns(connection: sqlite3.Connection) -> None:
    """Apply only the source-audited 0041 additions to synthetic metric fixtures."""
    connection.execute(
        "ALTER TABLE computed_metric_definitions "
        "ADD COLUMN definition_kind VARCHAR(40) NOT NULL DEFAULT 'scalar'"
    )
    connection.execute("ALTER TABLE computed_metric_definitions ADD COLUMN configuration_json JSON")
    connection.execute(
        "ALTER TABLE computed_metric_results "
        "ADD COLUMN result_kind VARCHAR(40) NOT NULL DEFAULT 'scalar'"
    )


@pytest.mark.parametrize(
    ("revision", "strict", "expected_status"),
    [
        ("0038", True, 2),
        ("0038", False, 0),
        ("0037", True, 2),
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
        connection.execute("INSERT INTO alembic_version VALUES ('0039')")
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
        connection.execute("INSERT INTO alembic_version VALUES ('0039')")
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
        connection.execute("INSERT INTO alembic_version VALUES ('0039')")
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


@pytest.mark.parametrize(
    "retained_tables",
    [
        ("environmental_analysis_definitions",),
        ("environmental_analysis_results",),
        ("environmental_analysis_definitions", "environmental_analysis_results"),
    ],
)
def test_0042_analysis_requires_0040_event_predecessor(
    tmp_path: Path, retained_tables: tuple[str, ...]
) -> None:
    """An apparently complete 0042 analysis pair can still lack 0040 history."""
    database = tmp_path / "partial-0042.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0042')")
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        for name in retained_tables:
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, note TEXT)")
            connection.execute(f"INSERT INTO {name} (id, note) VALUES (1, 'research-keep')")
        connection.execute("CREATE TABLE biological_sentinel (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES (1, 'biological-keep')")
    before = database.read_bytes()
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2, completed.stderr
    report = json.loads(completed.stdout)
    assert report["revision_rows"] == ["0042"]
    assert report["lineage_hint"] == "scientific"
    assert "environmental_analysis_without_event_definitions" in report["warnings"]
    if len(retained_tables) == 2:
        assert "incomplete_environmental_analysis_schema_family" not in report["warnings"]
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        for name in retained_tables:
            assert connection.execute(f"SELECT note FROM {name}").fetchone() == ("research-keep",)
        assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
            "biological-keep",
        )


@pytest.mark.parametrize(
    ("revision", "extensions"),
    [
        ("0039", ()),
        ("0040", ("environmental_event_definitions",)),
        (
            "0042",
            (
                "environmental_event_definitions",
                "environmental_analysis_definitions",
                "environmental_analysis_results",
            ),
        ),
    ],
)
def test_legitimate_11_extension_stages_do_not_require_later_tables(
    tmp_path: Path, revision: str, extensions: tuple[str, ...]
) -> None:
    database = tmp_path / "staged-science.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
            *extensions,
        ):
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        if revision in {"0041", "0042"}:
            _add_0041_aggregate_columns(connection)
    before = database.read_bytes()
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["warnings"] == []
    assert report["lineage_hint"] == "scientific"
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before


@pytest.mark.parametrize(
    ("revision", "tables", "expected_warnings"),
    [
        (
            "0038",
            ("scientific_records", "environmental_cache_entries"),
            ("revision_0038_requires_schema_lineage_reconciliation",),
        ),
        (
            "0039",
            (
                "scientific_records",
                "environmental_cache_entries",
                "computed_metric_definitions",
                "computed_metric_results",
            ),
            (),
        ),
        (
            "0040",
            (
                "scientific_records",
                "environmental_cache_entries",
                "computed_metric_definitions",
                "computed_metric_results",
                "environmental_event_definitions",
            ),
            (),
        ),
        (
            "0042",
            (
                "scientific_records",
                "environmental_cache_entries",
                "computed_metric_definitions",
                "computed_metric_results",
                "environmental_event_definitions",
                "environmental_analysis_definitions",
                "environmental_analysis_results",
            ),
            (),
        ),
    ],
)
def test_scientific_11_revision_stages_are_not_false_partial_schemas(
    tmp_path: Path, revision: str, tables: tuple[str, ...], expected_warnings: tuple[str, ...]
) -> None:
    database = tmp_path / "scientific-stage.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for name in tables:
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        if revision in {"0041", "0042"}:
            _add_0041_aggregate_columns(connection)
        connection.execute("CREATE TABLE biological_sentinel (id INTEGER, note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES (1, 'coral-preserve')")
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (2 if expected_warnings else 0), result.stderr
    report = json.loads(result.stdout)
    assert report["warnings"] == list(expected_warnings)
    assert report["lineage_hint"] == "scientific"
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
            "coral-preserve",
        )


@pytest.mark.parametrize(
    ("revision", "tables", "expected_warnings"),
    [
        (
            "0038",
            ("scientific_records",),
            ("incomplete_scientific_schema_family",),
        ),
        (
            "0039",
            ("computed_metric_definitions",),
            (
                "incomplete_scientific_schema_family",
                "computed_metrics_without_scientific_base",
            ),
        ),
        (
            "0039",
            ("computed_metric_definitions", "computed_metric_results"),
            ("computed_metrics_without_scientific_base",),
        ),
        (
            "0040",
            (
                "scientific_records",
                "environmental_cache_entries",
                "environmental_event_definitions",
            ),
            ("environmental_event_without_computed_metrics",),
        ),
        (
            "0042",
            (
                "scientific_records",
                "environmental_cache_entries",
                "environmental_event_definitions",
                "environmental_analysis_definitions",
                "environmental_analysis_results",
            ),
            (
                "environmental_event_without_computed_metrics",
                "environmental_analysis_without_computed_metrics",
            ),
        ),
        (
            "0042",
            (
                "scientific_records",
                "environmental_cache_entries",
                "environmental_analysis_definitions",
                "environmental_analysis_results",
            ),
            (
                "environmental_analysis_without_computed_metrics",
                "environmental_analysis_without_event_definitions",
            ),
        ),
    ],
)
def test_broken_scientific_stage_dependencies_are_read_only_and_fail_closed(
    tmp_path: Path, revision: str, tables: tuple[str, ...], expected_warnings: tuple[str, ...]
) -> None:
    database = tmp_path / "broken-scientific-stage.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for name in tables:
            connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, note TEXT)")
            connection.execute(f"INSERT INTO {name} VALUES (1, 'research-preserve')")
        connection.execute("CREATE TABLE biological_sentinel (id INTEGER, note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES (1, 'coral-preserve')")
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    for warning in expected_warnings:
        assert warning in report["warnings"]
    assert report["lineage_hint"] == "scientific"
    assert report["upgrade_authorized"] is False
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        for name in tables:
            assert connection.execute(f'SELECT note FROM "{name}"').fetchone() == (
                "research-preserve",
            )
        assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
            "coral-preserve",
        )


@pytest.mark.parametrize(
    ("revision", "tables", "expected_warnings"),
    [
        (
            "0038",
            ("review_queue_item_events",),
            ("revision_0038_requires_schema_lineage_reconciliation",),
        ),
        ("0039", ("review_queue_item_events",), ()),
        ("0040", ("review_queue_item_events",), ()),
        ("0041", ("review_queue_item_events", "review_queue_bulk_requests"), ()),
        (
            "0037",
            ("review_queue_item_events",),
            ("qc_events_before_revision_0038",),
        ),
        (
            "0039",
            ("review_queue_bulk_requests",),
            (
                "qc_bulk_registry_without_review_events",
                "qc_bulk_registry_before_revision_0041",
            ),
        ),
        (
            "0041",
            ("review_queue_bulk_requests",),
            ("qc_bulk_registry_without_review_events",),
        ),
        (
            "0040",
            ("review_queue_item_events", "review_queue_bulk_requests"),
            ("qc_bulk_registry_before_revision_0041",),
        ),
        (
            "0041",
            ("review_queue_item_events",),
            ("qc_0041_missing_bulk_registry",),
        ),
    ],
)
def test_qc_16_migration_stages_preserve_records_and_diagnose_interrupted_ddl(
    tmp_path: Path, revision: str, tables: tuple[str, ...], expected_warnings: tuple[str, ...]
) -> None:
    """A legitimate 0038-0040 review audit must not require 0041 bulk DDL."""
    database = tmp_path / "qc-stage.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for table in tables:
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, note TEXT)')
            connection.execute(f'INSERT INTO "{table}" VALUES (1, ?)', ("review-preserve",))
        connection.execute("CREATE TABLE biological_sentinel (id INTEGER, note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES (1, 'coral-preserve')")
    before = database.read_bytes()
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == (2 if expected_warnings else 0), result.stderr
        report = json.loads(result.stdout)
        assert report["warnings"] == list(expected_warnings)
        assert report["lineage_hint"] == "qc"
        assert report["upgrade_authorized"] is False
        assert database.read_bytes() == before
        with sqlite3.connect(database) as connection:
            for table in tables:
                assert connection.execute(f'SELECT note FROM "{table}"').fetchone() == (
                    "review-preserve",
                )
            assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
                "coral-preserve",
            )


@pytest.mark.parametrize("revision", ["0039", "0040", "0041", "0042"])
@pytest.mark.parametrize(
    "retained_metrics", [(), ("computed_metric_definitions",), ("computed_metric_results",)]
)
def test_scientific_stamp_requires_computed_metric_pair(
    tmp_path: Path, revision: str, retained_metrics: tuple[str, ...]
) -> None:
    """A later revision cannot prove missing immutable formula/result tables exist."""
    database = tmp_path / "missing-metric-stage.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for table in ("scientific_records", "environmental_cache_entries", *retained_metrics):
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, note TEXT)')
            connection.execute(f'INSERT INTO "{table}" VALUES (1, ?)', ("private coral count",))
    original = database.read_bytes()
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2, result.stderr
        report = json.loads(result.stdout)
        assert report["lineage_hint"] == "scientific"
        assert "scientific_revision_missing_computed_metric_pair" in report["warnings"]
        assert report["upgrade_authorized"] is False
        assert "private coral count" not in result.stdout
        assert database.read_bytes() == original
        assert report["inventory"]["scientific_records"]["rows"] == 1


@pytest.mark.parametrize(
    ("revision", "extensions", "expected_warnings"),
    [
        (
            "0038",
            ("environmental_event_definitions",),
            (
                "computed_metrics_before_revision_0039",
                "environmental_event_before_revision_0040",
                "revision_0038_requires_schema_lineage_reconciliation",
            ),
        ),
        (
            "0039",
            ("environmental_event_definitions",),
            ("environmental_event_before_revision_0040",),
        ),
        (
            "0039",
            (
                "environmental_event_definitions",
                "environmental_analysis_definitions",
                "environmental_analysis_results",
            ),
            (
                "environmental_event_before_revision_0040",
                "environmental_analysis_before_revision_0042",
            ),
        ),
        ("0040", ("environmental_event_definitions",), ()),
        (
            "0040",
            (
                "environmental_event_definitions",
                "environmental_analysis_definitions",
                "environmental_analysis_results",
            ),
            ("environmental_analysis_before_revision_0042",),
        ),
        ("0041", ("environmental_event_definitions",), ()),
        (
            "0041",
            (
                "environmental_event_definitions",
                "environmental_analysis_definitions",
                "environmental_analysis_results",
            ),
            ("environmental_analysis_before_revision_0042",),
        ),
        (
            "0042",
            (
                "environmental_event_definitions",
                "environmental_analysis_definitions",
                "environmental_analysis_results",
            ),
            (),
        ),
        ("0040", (), ("scientific_revision_missing_environmental_event_definitions",)),
        ("0041", (), ("scientific_revision_missing_environmental_event_definitions",)),
        (
            "0042",
            (),
            (
                "scientific_revision_missing_environmental_event_definitions",
                "scientific_revision_missing_environmental_analysis_pair",
            ),
        ),
        (
            "0042",
            ("environmental_event_definitions",),
            ("scientific_revision_missing_environmental_analysis_pair",),
        ),
    ],
)
def test_scientific_extension_migration_stamp_is_stage_aware_and_read_only(
    tmp_path: Path,
    revision: str,
    extensions: tuple[str, ...],
    expected_warnings: tuple[str, ...],
) -> None:
    """Never mistake future scientific DDL for completed earlier migrations."""
    database = tmp_path / "stale-scientific-stamp.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for table in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
            *extensions,
        ):
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, note TEXT)')
            connection.execute(f'INSERT INTO "{table}" VALUES (1, ?)', ("scientific-preserve",))
        if revision in {"0041", "0042"}:
            _add_0041_aggregate_columns(connection)
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES ('coral-preserve')")
    original_bytes = database.read_bytes()
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == (2 if expected_warnings else 0), result.stderr
        report = json.loads(result.stdout)
        assert report["warnings"] == list(expected_warnings)
        assert report["lineage_hint"] == "scientific"
        assert report["upgrade_authorized"] is False
        assert database.read_bytes() == original_bytes
        with sqlite3.connect(database) as connection:
            for table in extensions:
                assert connection.execute(f'SELECT note FROM "{table}"').fetchone() == (
                    "scientific-preserve",
                )
            assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
                "coral-preserve",
            )


@pytest.mark.parametrize(
    ("revision", "tables", "expected_warnings"),
    [
        (
            "0014",
            ("scientific_records", "environmental_cache_entries"),
            ("scientific_base_before_revision_0038",),
        ),
        (
            "0037",
            ("scientific_records", "environmental_cache_entries"),
            ("scientific_base_before_revision_0038",),
        ),
        (
            "0037",
            (
                "scientific_records",
                "environmental_cache_entries",
                "computed_metric_definitions",
                "computed_metric_results",
            ),
            ("scientific_base_before_revision_0038", "computed_metrics_before_revision_0039"),
        ),
        (
            "0038",
            (
                "scientific_records",
                "environmental_cache_entries",
                "computed_metric_definitions",
                "computed_metric_results",
            ),
            (
                "computed_metrics_before_revision_0039",
                "revision_0038_requires_schema_lineage_reconciliation",
            ),
        ),
        (
            "0038",
            ("scientific_records", "environmental_cache_entries"),
            ("revision_0038_requires_schema_lineage_reconciliation",),
        ),
        (
            "0039",
            (
                "scientific_records",
                "environmental_cache_entries",
                "computed_metric_definitions",
                "computed_metric_results",
            ),
            (),
        ),
    ],
)
@pytest.mark.parametrize("strict", [False, True])
def test_11_scientific_tables_cannot_precede_their_revision(
    tmp_path: Path,
    revision: str,
    tables: tuple[str, ...],
    expected_warnings: tuple[str, ...],
    strict: bool,
) -> None:
    """Preserve source observations when a stale stamp hides 1.1 migration DDL."""
    database = tmp_path / "stale-scientific-stage.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for table in tables:
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, note TEXT)')
            connection.execute(f'INSERT INTO "{table}" VALUES (1, ?)', ("scientific-keep",))
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES ('coral-keep')")
    original_bytes = database.read_bytes()
    for _ in range(2):
        command = [sys.executable, str(SCRIPT)]
        if strict:
            command.append("--fail-on-warning")
        result = subprocess.run(
            [*command, str(database)], capture_output=True, text=True, check=False
        )
        assert result.returncode == (2 if strict and expected_warnings else 0), result.stderr
        report = json.loads(result.stdout)
        assert report["warnings"] == list(expected_warnings)
        assert report["upgrade_authorized"] is False
        assert report["lineage_hint"] == "scientific"
        assert database.read_bytes() == original_bytes
        with sqlite3.connect(database) as connection:
            for table in tables:
                assert connection.execute(f'SELECT note FROM "{table}"').fetchone() == (
                    "scientific-keep",
                )
            assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
                "coral-keep",
            )


@pytest.mark.parametrize(
    ("variant", "mismatch"),
    [
        ("canonical", False),
        ("additional_nonunique_index", False),
        ("partial_unique_replaces_request_constraint", True),
        ("request_unique_nocase", True),
        ("request_unique_descending", True),
        ("request_unique_nocase_descending", True),
        ("request_unique_renamed", True),
        ("request_unique_unnamed", True),
        ("duplicate_project_fk", True),
        ("additional_unique_actor", True),
        ("additional_partial_unique_actor", True),
        ("stage_0038_0038", False),
        ("stage_0038_0039", True),
        ("stage_0038_0040", True),
        ("stage_0039_0038", True),
        ("stage_0039_0039", False),
        ("stage_0039_0040", True),
        ("stage_0040_0038", True),
        ("stage_0040_0039", True),
        ("stage_0040_0040", False),
        ("stage_0041_0038", True),
        ("stage_0041_0039", True),
        ("stage_0041_0040", False),
    ],
)
def test_0038_qc_structural_audit_rejects_unreviewed_unique_index_semantics(
    tmp_path: Path, variant: str, mismatch: bool
) -> None:
    """A column-matching QC table can lose idempotency or its stamped event vocabulary."""
    database = tmp_path / "review-events.sqlite"
    revision, event_stage = ("0039", "0039")
    if variant.startswith("stage_"):
        _, revision, event_stage = variant.split("_")
    event_types = "'comment', 'assign', 'unassign'"
    if event_stage in {"0039", "0040"}:
        event_types += ", 'triage_start', 'triage_skip', 'triage_return'"
    if event_stage == "0040":
        event_types += ", 'triage_complete'"
    has_request_constraint = variant != "partial_unique_replaces_request_constraint"
    request_indexed_column = "client_request_id"
    if variant in {"request_unique_nocase", "request_unique_nocase_descending"}:
        request_indexed_column += " COLLATE NOCASE"
    if variant in {"request_unique_descending", "request_unique_nocase_descending"}:
        request_indexed_column += " DESC"
    request_constraint = (
        ", CONSTRAINT uq_review_queue_item_event_request "
        f"UNIQUE (review_queue_item_id, {request_indexed_column})"
        if has_request_constraint
        else ""
    )
    if variant == "request_unique_renamed":
        request_constraint = request_constraint.replace(
            "uq_review_queue_item_event_request", "renamed_request_constraint"
        )
    elif variant == "request_unique_unnamed":
        request_constraint = request_constraint.replace(
            "CONSTRAINT uq_review_queue_item_event_request ", ""
        )
    duplicate_fk = (
        ", FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
        if variant == "duplicate_project_fk"
        else ""
    )
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        if revision == "0041":
            connection.execute(
                "CREATE TABLE review_queue_bulk_requests ("
                "id VARCHAR(36) NOT NULL PRIMARY KEY, "
                "review_queue_id VARCHAR(36) NOT NULL "
                "REFERENCES review_queues(id) ON DELETE RESTRICT, "
                "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE RESTRICT, "
                "action VARCHAR(20) NOT NULL, actor VARCHAR(100) NOT NULL, "
                "reason TEXT, item_ids_json JSON NOT NULL, created_at DATETIME NOT NULL)"
            )
        connection.execute("CREATE TABLE projects (id TEXT NOT NULL PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE review_queues (id TEXT NOT NULL PRIMARY KEY, project_id TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE review_queue_items "
            "(id TEXT NOT NULL PRIMARY KEY, project_id TEXT NOT NULL, "
            "review_queue_id TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE review_queue_item_events ("
            "id VARCHAR(36) NOT NULL PRIMARY KEY, "
            "review_queue_id VARCHAR(36) NOT NULL "
            "REFERENCES review_queues(id) ON DELETE CASCADE, "
            "review_queue_item_id VARCHAR(36) NOT NULL "
            "REFERENCES review_queue_items(id) ON DELETE CASCADE, "
            "project_id VARCHAR(36) NOT NULL "
            "REFERENCES projects(id) ON DELETE CASCADE, "
            "client_request_id VARCHAR(36) NOT NULL, "
            "event_type VARCHAR(20) NOT NULL, "
            "actor VARCHAR(100) NOT NULL, "
            "comment TEXT, assignee VARCHAR(100), created_at DATETIME NOT NULL"
            f"{request_constraint}{duplicate_fk}, "
            "CONSTRAINT ck_review_queue_item_event_type "
            f"CHECK (event_type IN ({event_types})))"
        )
        connection.execute(
            "CREATE INDEX ix_review_queue_item_events_item_created "
            "ON review_queue_item_events (review_queue_item_id, created_at)"
        )
        connection.execute(
            "CREATE INDEX ix_review_queue_item_events_queue_created "
            "ON review_queue_item_events (review_queue_id, created_at)"
        )
        if variant == "partial_unique_replaces_request_constraint":
            connection.execute(
                "CREATE UNIQUE INDEX only_one_reviewer_request "
                "ON review_queue_item_events (review_queue_item_id, client_request_id) "
                "WHERE actor = 'researcher-a'"
            )
        elif variant == "additional_unique_actor":
            connection.execute(
                "CREATE UNIQUE INDEX unreviewed_actor_limit ON review_queue_item_events (actor)"
            )
        elif variant == "additional_partial_unique_actor":
            connection.execute(
                "CREATE UNIQUE INDEX unreviewed_partial_actor_limit "
                "ON review_queue_item_events (actor) WHERE event_type = 'comment'"
            )
        elif variant == "additional_nonunique_index":
            connection.execute(
                "CREATE INDEX benign_actor_lookup ON review_queue_item_events (actor)"
            )
        connection.execute("INSERT INTO projects VALUES ('project')")
        connection.execute("INSERT INTO review_queues VALUES ('queue', 'project')")
        connection.execute("INSERT INTO review_queue_items VALUES ('item', 'project', 'queue')")
        connection.execute(
            "INSERT INTO review_queue_item_events "
            "(id, review_queue_id, review_queue_item_id, project_id, "
            "client_request_id, event_type, actor, comment, created_at) "
            "VALUES ('event', 'queue', 'item', 'project', "
            "'request', 'comment', 'researcher-a', 'private coral review', "
            "'2026-11-16T00:00:00Z')"
        )
        connection.execute("CREATE TABLE biological_sentinel (note TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO biological_sentinel VALUES ('private original coral observation')"
        )
    original = database.read_bytes()
    expected_warning = "lineage_table_contract_mismatch_review_queue_item_events"
    for _ in range(2):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--verify-structural-contracts",
                "--fail-on-warning",
                str(database),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        expected_returncode = 2 if mismatch or revision == "0038" else 0
        assert completed.returncode == expected_returncode, completed.stderr
        report = json.loads(completed.stdout)
        assert report["upgrade_authorized"] is False
        assert report["structural_contracts"]["review_queue_item_events"] == (
            "mismatch" if mismatch else "matches"
        )
        assert (expected_warning in report["warnings"]) is mismatch
        assert "private coral review" not in completed.stdout
        assert "private original coral observation" not in completed.stdout
        assert database.read_bytes() == original
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT comment FROM review_queue_item_events").fetchone() == (
            "private coral review",
        )
        assert connection.execute("SELECT note FROM biological_sentinel").fetchone() == (
            "private original coral observation",
        )


@pytest.mark.parametrize(
    ("variant", "mismatch_table"),
    [
        ("canonical", None),
        ("extra_cache_lookup_index", None),
        ("cache_json_as_text", "environmental_cache_entries"),
        ("cache_expiry_as_integer", "environmental_cache_entries"),
        ("cache_source_url_shortened", "environmental_cache_entries"),
        ("cache_missing_unique", "environmental_cache_entries"),
        ("cache_unique_renamed", "environmental_cache_entries"),
        ("cache_unique_unnamed", "environmental_cache_entries"),
        ("cache_unique_nocase", "environmental_cache_entries"),
        ("cache_fk_restrict", "environmental_cache_entries"),
        ("science_json_as_text", "scientific_records"),
        ("science_observed_as_integer", "scientific_records"),
        ("science_variable_shortened", "scientific_records"),
    ],
)
def test_0038_scientific_cache_and_declared_type_contracts(
    tmp_path: Path, variant: str, mismatch_table: str | None
) -> None:
    """Classify both source-audited 1.1 0038 tables without trusting equal stamps."""
    database = tmp_path / "scientific-lineage.sqlite"
    science_sql = (
        "CREATE TABLE scientific_records ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "variable VARCHAR(100) NOT NULL, source_kind VARCHAR(30) NOT NULL, "
        "observed_at DATETIME NOT NULL, "
        "image_id VARCHAR(36) REFERENCES images(id) ON DELETE RESTRICT, "
        "video_id VARCHAR(36) REFERENCES videos(id) ON DELETE RESTRICT, "
        "track_id VARCHAR(36) REFERENCES video_tracks(id) ON DELETE RESTRICT, "
        "model_run_id VARCHAR(36) REFERENCES jobs(id) ON DELETE RESTRICT, "
        "payload_json JSON NOT NULL, content_sha256 VARCHAR(64) NOT NULL, "
        "created_at DATETIME NOT NULL)"
    )
    cache_sql = (
        "CREATE TABLE environmental_cache_entries ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "cache_key VARCHAR(64) NOT NULL, source_url VARCHAR(2000) NOT NULL, "
        "payload_json JSON NOT NULL, content_sha256 VARCHAR(64) NOT NULL, "
        "fetched_at DATETIME NOT NULL, expires_at DATETIME NOT NULL, "
        "CONSTRAINT uq_environmental_cache_project_key UNIQUE (project_id, cache_key))"
    )
    replacements = {
        "science_json_as_text": ("payload_json JSON NOT NULL", "payload_json TEXT NOT NULL"),
        "science_observed_as_integer": (
            "observed_at DATETIME NOT NULL",
            "observed_at INTEGER NOT NULL",
        ),
        "science_variable_shortened": (
            "variable VARCHAR(100) NOT NULL",
            "variable VARCHAR(10) NOT NULL",
        ),
        "cache_json_as_text": ("payload_json JSON NOT NULL", "payload_json TEXT NOT NULL"),
        "cache_expiry_as_integer": (
            "expires_at DATETIME NOT NULL",
            "expires_at INTEGER NOT NULL",
        ),
        "cache_source_url_shortened": (
            "source_url VARCHAR(2000) NOT NULL",
            "source_url VARCHAR(200) NOT NULL",
        ),
        "cache_missing_unique": (
            ", CONSTRAINT uq_environmental_cache_project_key UNIQUE (project_id, cache_key)",
            "",
        ),
        "cache_unique_renamed": ("uq_environmental_cache_project_key", "renamed_cache_key"),
        "cache_unique_unnamed": ("CONSTRAINT uq_environmental_cache_project_key ", ""),
        "cache_unique_nocase": (
            "UNIQUE (project_id, cache_key)",
            "UNIQUE (project_id, cache_key COLLATE NOCASE)",
        ),
        "cache_fk_restrict": (
            "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
            "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE RESTRICT",
        ),
    }
    if variant in replacements:
        old, new = replacements[variant]
        target = science_sql if variant.startswith("science_") else cache_sql
        assert target.count(old) == 1
        if variant.startswith("science_"):
            science_sql = target.replace(old, new)
        else:
            cache_sql = target.replace(old, new)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('0039')")
        for parent in (
            "projects",
            "images",
            "videos",
            "video_tracks",
            "jobs",
            "workflow_runs",
            "workflow_node_runs",
        ):
            connection.execute(f'CREATE TABLE "{parent}" (id VARCHAR(36) PRIMARY KEY)')
        connection.execute(science_sql)
        connection.execute(cache_sql)
        # Revision 0039 also creates the metric pair. Keep the fixture complete
        # so this test isolates the 0038 structural-contract variants.
        _create_0039_metric_pair(connection)
        connection.execute(
            "CREATE INDEX ix_scientific_project_variable_time "
            "ON scientific_records (project_id, variable, observed_at)"
        )
        if variant == "extra_cache_lookup_index":
            connection.execute(
                "CREATE INDEX extra_cache_lookup ON environmental_cache_entries (fetched_at)"
            )
        connection.execute("INSERT INTO projects VALUES ('project-1')")
        connection.execute(
            "INSERT INTO scientific_records "
            "(id, project_id, variable, source_kind, observed_at, payload_json, "
            "content_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "science-1",
                "project-1",
                "coral_polyp_count",
                "manual",
                "2026-11-18 12:00:00",
                '{"count":7,"private":"reef site A"}',
                "a" * 64,
                "2026-11-18 12:01:00",
            ),
        )
        connection.execute(
            "INSERT INTO environmental_cache_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "cache-1",
                "project-1",
                "local-observation",
                "https://invalid.example/private",
                '{"temperature_c":20.2}',
                "b" * 64,
                "2026-11-18 12:02:00",
                "2026-11-18 12:03:00",
            ),
        )
    original = database.read_bytes()
    for _ in range(2):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--verify-structural-contracts",
                "--fail-on-warning",
                str(database),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == (2 if mismatch_table else 0), completed.stderr
        report = json.loads(completed.stdout)
        assert report["upgrade_authorized"] is False
        assert report["lineage_hint"] == "scientific"
        for table in ("scientific_records", "environmental_cache_entries"):
            expected = "mismatch" if table == mismatch_table else "matches"
            assert report["structural_contracts"][table] == expected
            warning = f"lineage_table_contract_mismatch_{table}"
            assert (warning in report["warnings"]) is (table == mismatch_table)
        assert "reef site A" not in completed.stdout + completed.stderr
        assert "temperature_c" not in completed.stdout + completed.stderr
        assert database.read_bytes() == original
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT payload_json FROM scientific_records").fetchone() == (
            '{"count":7,"private":"reef site A"}',
        )
        assert connection.execute(
            "SELECT payload_json FROM environmental_cache_entries"
        ).fetchone() == ('{"temperature_c":20.2}',)


@pytest.mark.parametrize("revision", ["0039", "0040", "0041", "0042"])
@pytest.mark.parametrize("column_mask", range(8))
def test_0041_annotation_aggregate_columns_match_scientific_revision(
    tmp_path: Path, revision: str, column_mask: int
) -> None:
    """Reject partial and premature 0041 column additions without changing research."""
    database = tmp_path / "aggregate-stage.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for table in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, note TEXT)')
            connection.execute(f'INSERT INTO "{table}" VALUES (1, ?)', ("private coral count",))
        if revision in {"0040", "0041", "0042"}:
            connection.execute("CREATE TABLE environmental_event_definitions (id INTEGER)")
        if revision == "0042":
            connection.execute("CREATE TABLE environmental_analysis_definitions (id INTEGER)")
            connection.execute("CREATE TABLE environmental_analysis_results (id INTEGER)")
        additions = (
            "ALTER TABLE computed_metric_definitions "
            "ADD COLUMN definition_kind VARCHAR(40) NOT NULL DEFAULT 'scalar'",
            "ALTER TABLE computed_metric_definitions ADD COLUMN configuration_json JSON",
            "ALTER TABLE computed_metric_results "
            "ADD COLUMN result_kind VARCHAR(40) NOT NULL DEFAULT 'scalar'",
        )
        for index, statement in enumerate(additions):
            if column_mask & (1 << index):
                connection.execute(statement)
    expected = []
    if revision in {"0041", "0042"} and column_mask != 7:
        expected.append("scientific_revision_missing_annotation_aggregate_columns")
    if revision in {"0039", "0040"} and column_mask:
        expected.append("annotation_aggregate_columns_before_revision_0041")
    original = database.read_bytes()
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == (2 if expected else 0), result.stderr
        report = json.loads(result.stdout)
        assert report["warnings"] == expected
        assert report["lineage_hint"] == "scientific"
        assert report["upgrade_authorized"] is False
        assert "private coral count" not in result.stdout
        assert report["inventory"]["computed_metric_results"]["rows"] == 1
        assert database.read_bytes() == original


@pytest.mark.parametrize("revision", ["0041", "0042"])
@pytest.mark.parametrize(
    ("column_index", "declaration"),
    [
        (None, None),
        (0, "definition_kind TEXT NOT NULL DEFAULT 'scalar'"),
        (0, "definition_kind VARCHAR(40) DEFAULT 'scalar'"),
        (0, "definition_kind VARCHAR(40) NOT NULL"),
        (1, "configuration_json TEXT"),
        (1, "configuration_json JSON NOT NULL"),
        (1, "configuration_json JSON DEFAULT '{}'"),
        (2, "result_kind VARCHAR(40) NOT NULL DEFAULT 'aggregate'"),
        (2, "result_kind VARCHAR(40) DEFAULT 'scalar'"),
    ],
)
def test_0041_annotation_aggregate_column_contract(
    tmp_path: Path, revision: str, column_index: int | None, declaration: str | None
) -> None:
    """Identical historical values cannot prove the original future-write contract."""
    database = tmp_path / "aggregate-contract.sqlite"
    declarations = [
        "definition_kind VARCHAR(40) NOT NULL DEFAULT 'scalar'",
        "configuration_json JSON",
        "result_kind VARCHAR(40) NOT NULL DEFAULT 'scalar'",
    ]
    if column_index is not None:
        assert declaration is not None
        declarations[column_index] = declaration
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for table in (
            "scientific_records",
            "environmental_cache_entries",
            "environmental_event_definitions",
        ):
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        if revision == "0042":
            connection.execute("CREATE TABLE environmental_analysis_definitions (id INTEGER)")
            connection.execute("CREATE TABLE environmental_analysis_results (id INTEGER)")
        connection.execute(
            "CREATE TABLE computed_metric_definitions "
            f"(id INTEGER PRIMARY KEY, {declarations[0]}, {declarations[1]})"
        )
        connection.execute(
            f"CREATE TABLE computed_metric_results (id INTEGER PRIMARY KEY, {declarations[2]})"
        )
        connection.execute("INSERT INTO computed_metric_definitions VALUES (1, 'scalar', '{}')")
        connection.execute("INSERT INTO computed_metric_results VALUES (1, 'scalar')")
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES ('private coral count')")
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    expected = (
        [] if column_index is None else ["scientific_annotation_aggregate_column_contract_mismatch"]
    )
    original = database.read_bytes()
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == (2 if expected else 0), result.stderr
        report = json.loads(result.stdout)
        assert report["warnings"] == expected
        assert report["lineage_hint"] == "scientific"
        assert report["upgrade_authorized"] is False
        assert "private coral count" not in result.stdout
        assert report["inventory"]["computed_metric_results"]["rows"] == 1
        assert database.read_bytes() == original


@pytest.mark.parametrize(
    ("variant", "mismatch"),
    [
        ("canonical", None),
        ("event_query_type", "environmental_event_definitions"),
        ("event_index_partial", "environmental_event_definitions"),
        ("definition_hash_nullable", "environmental_analysis_definitions"),
        ("result_definition_cascade", "environmental_analysis_results"),
        ("result_missing_unique", "environmental_analysis_results"),
        ("result_unique_renamed", "environmental_analysis_results"),
        ("result_unique_unnamed", "environmental_analysis_results"),
        ("result_missing_provenance", "environmental_analysis_results"),
        ("result_trigger", "environmental_analysis_results"),
    ],
)
def test_environmental_extension_structural_contracts(
    tmp_path: Path, variant: str, mismatch: str | None
) -> None:
    """Audit real 0040/0042 schema shapes without exposing private research."""
    database = tmp_path / "environmental-contract.sqlite"
    science_sql = (
        "CREATE TABLE scientific_records ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "variable VARCHAR(100) NOT NULL, source_kind VARCHAR(30) NOT NULL, "
        "observed_at DATETIME NOT NULL, "
        "image_id VARCHAR(36) REFERENCES images(id) ON DELETE RESTRICT, "
        "video_id VARCHAR(36) REFERENCES videos(id) ON DELETE RESTRICT, "
        "track_id VARCHAR(36) REFERENCES video_tracks(id) ON DELETE RESTRICT, "
        "model_run_id VARCHAR(36) REFERENCES jobs(id) ON DELETE RESTRICT, "
        "payload_json JSON NOT NULL, content_sha256 VARCHAR(64) NOT NULL, "
        "created_at DATETIME NOT NULL)"
    )
    cache_sql = (
        "CREATE TABLE environmental_cache_entries ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "cache_key VARCHAR(64) NOT NULL, source_url VARCHAR(2000) NOT NULL, "
        "payload_json JSON NOT NULL, content_sha256 VARCHAR(64) NOT NULL, "
        "fetched_at DATETIME NOT NULL, expires_at DATETIME NOT NULL, "
        "CONSTRAINT uq_environmental_cache_project_key UNIQUE (project_id, cache_key))"
    )
    event_sql = (
        "CREATE TABLE environmental_event_definitions ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "name VARCHAR(200) NOT NULL, query_json JSON NOT NULL, "
        "definition_sha256 VARCHAR(64) NOT NULL, created_at DATETIME NOT NULL)"
    )
    definition_sql = (
        "CREATE TABLE environmental_analysis_definitions ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "analysis_kind VARCHAR(50) NOT NULL, name VARCHAR(200) NOT NULL, "
        "configuration_json JSON NOT NULL, calculation_version VARCHAR(100) NOT NULL, "
        "definition_sha256 VARCHAR(64) NOT NULL, created_at DATETIME NOT NULL)"
    )
    result_sql = (
        "CREATE TABLE environmental_analysis_results ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "definition_id VARCHAR(36) NOT NULL "
        "REFERENCES environmental_analysis_definitions(id) ON DELETE RESTRICT, "
        "analysis_kind VARCHAR(50) NOT NULL, observed_at DATETIME NOT NULL, "
        "payload_json JSON NOT NULL, input_snapshot_json JSON NOT NULL, "
        "source_record_ids_json JSON NOT NULL, source_analysis_result_ids_json JSON NOT NULL, "
        "quality_control_json JSON NOT NULL, uncertainty_json JSON, "
        "content_sha256 VARCHAR(64) NOT NULL, "
        "workflow_run_id VARCHAR(36) REFERENCES workflow_runs(id) ON DELETE RESTRICT, "
        "workflow_node_run_id VARCHAR(36) REFERENCES workflow_node_runs(id) ON DELETE RESTRICT, "
        "created_at DATETIME NOT NULL, "
        "CONSTRAINT uq_environmental_analysis_result_workflow_node_run "
        "UNIQUE (workflow_node_run_id))"
    )
    if variant == "event_query_type":
        event_sql = event_sql.replace("query_json JSON", "query_json TEXT")
    if variant == "definition_hash_nullable":
        definition_sql = definition_sql.replace(
            "definition_sha256 VARCHAR(64) NOT NULL", "definition_sha256 VARCHAR(64)"
        )
    if variant == "result_definition_cascade":
        result_sql = result_sql.replace(
            "environmental_analysis_definitions(id) ON DELETE RESTRICT",
            "environmental_analysis_definitions(id) ON DELETE CASCADE",
        )
    if variant == "result_missing_unique":
        result_sql = result_sql.replace(
            ", CONSTRAINT uq_environmental_analysis_result_workflow_node_run "
            "UNIQUE (workflow_node_run_id)",
            "",
        )
    if variant == "result_unique_renamed":
        result_sql = result_sql.replace(
            "uq_environmental_analysis_result_workflow_node_run", "renamed_analysis_result"
        )
    if variant == "result_unique_unnamed":
        result_sql = result_sql.replace(
            "CONSTRAINT uq_environmental_analysis_result_workflow_node_run ", ""
        )
    if variant == "result_missing_provenance":
        result_sql = result_sql.replace("input_snapshot_json JSON NOT NULL, ", "")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('0042')")
        for parent in (
            "projects",
            "images",
            "videos",
            "video_tracks",
            "jobs",
            "workflow_runs",
            "workflow_node_runs",
        ):
            connection.execute(f'CREATE TABLE "{parent}" (id VARCHAR(36) PRIMARY KEY)')
        connection.execute(science_sql)
        connection.execute(cache_sql)
        connection.execute(
            "CREATE INDEX ix_scientific_project_variable_time "
            "ON scientific_records (project_id, variable, observed_at)"
        )
        _create_0039_metric_pair(connection)
        _add_0041_aggregate_columns(connection)
        connection.execute(event_sql)
        connection.execute(definition_sql)
        connection.execute(result_sql)
        event_index = (
            "CREATE INDEX ix_environmental_event_definition_project "
            "ON environmental_event_definitions (project_id, created_at)"
        )
        if variant == "event_index_partial":
            event_index += " WHERE name <> ''"
        connection.execute(event_index)
        connection.execute(
            "CREATE INDEX ix_environmental_analysis_definition_project_kind "
            "ON environmental_analysis_definitions (project_id, analysis_kind, created_at)"
        )
        connection.execute(
            "CREATE INDEX ix_environmental_analysis_result_project_kind "
            "ON environmental_analysis_results (project_id, analysis_kind, created_at)"
        )
        connection.execute(
            "CREATE INDEX ix_environmental_analysis_result_definition "
            "ON environmental_analysis_results (definition_id, created_at)"
        )
        connection.execute("INSERT INTO projects VALUES ('project-1')")
        connection.execute(
            "INSERT INTO environmental_event_definitions VALUES (?, ?, ?, ?, ?, ?)",
            (
                "event-1",
                "project-1",
                "private reef location",
                '{"threshold_c":28}',
                "a" * 64,
                "2026-11-23 12:00:00",
            ),
        )
        if variant == "result_trigger":
            connection.execute(
                "CREATE TRIGGER alter_event AFTER INSERT ON environmental_analysis_results "
                "BEGIN UPDATE environmental_event_definitions SET name = 'changed'; END"
            )
    original = database.read_bytes()
    for _ in range(2):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--verify-structural-contracts",
                "--fail-on-warning",
                str(database),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == (2 if mismatch else 0), completed.stderr
        report = json.loads(completed.stdout)
        assert report["upgrade_authorized"] is False
        assert report["lineage_hint"] == "scientific"
        for table in (
            "environmental_event_definitions",
            "environmental_analysis_definitions",
            "environmental_analysis_results",
        ):
            assert report["structural_contracts"][table] == (
                "mismatch" if table == mismatch else "matches"
            )
            assert (f"lineage_table_contract_mismatch_{table}" in report["warnings"]) == (
                table == mismatch
            )
        assert "private reef location" not in completed.stdout + completed.stderr
        assert "threshold_c" not in completed.stdout + completed.stderr
        assert database.read_bytes() == original


@pytest.mark.parametrize(
    "table",
    [
        "scientific_records",
        "environmental_cache_entries",
        "computed_metric_definitions",
        "computed_metric_results",
        "environmental_event_definitions",
        "environmental_analysis_definitions",
        "environmental_analysis_results",
        "review_queue_item_events",
        "review_queue_bulk_requests",
    ],
)
@pytest.mark.parametrize("kind", ["table", "view"])
def test_reserved_lineage_schema_aliases_fail_closed(tmp_path: Path, table: str, kind: str) -> None:
    """SQLite resolves aliases even though the stored schema names differ."""
    database = tmp_path / "reserved-schema.sqlite"
    is_qc = table.startswith("review_queue_")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0039')")
        baseline = (
            (
                "scientific_records",
                "environmental_cache_entries",
                "computed_metric_definitions",
                "computed_metric_results",
            )
            if is_qc
            else ("review_queue_item_events",)
        )
        for name in baseline:
            connection.execute(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY)')
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute("INSERT INTO biological_sentinel VALUES ('private coral observation')")
        if kind == "table":
            connection.execute(f'CREATE TABLE "{table.upper()}" (id TEXT PRIMARY KEY)')
            connection.execute(
                f'INSERT INTO "{table.upper()}" VALUES (?)', ("private lineage record",)
            )
        else:
            connection.execute(f'CREATE VIEW "{table}" AS SELECT note FROM biological_sentinel')
        assert connection.execute(f'SELECT * FROM "{table}"').fetchone() is not None
    original = database.read_bytes()
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2, result.stderr
        report = json.loads(result.stdout)
        assert "noncanonical_lineage_schema_object" in report["warnings"]
        assert report["inventory"][table]["present"] is (kind == "table")
        expected_lineage = "ambiguous" if kind == "table" else "scientific" if is_qc else "qc"
        assert report["lineage_hint"] == expected_lineage
        assert report["upgrade_authorized"] is False
        assert "private coral observation" not in result.stdout + result.stderr
        assert "private lineage record" not in result.stdout + result.stderr
        assert database.read_bytes() == original


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("ALEMBIC_VERSION", "table"),
        ("Alembic_Version", "table"),
        ("alembic_version", "view"),
        ("ALEMBIC_VERSION", "view"),
        ("alembic_version", "table"),
    ],
)
def test_revision_schema_object_identity(tmp_path: Path, name: str, kind: str) -> None:
    database = tmp_path / "revision-object.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE biological_observations (version_num TEXT, note TEXT)")
        connection.execute(
            "INSERT INTO biological_observations VALUES ('0039', 'private coral observation')"
        )
        for table in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        if kind == "table":
            connection.execute(f'CREATE TABLE "{name}" (version_num TEXT NOT NULL PRIMARY KEY)')
            connection.execute(f'INSERT INTO "{name}" VALUES (?)', ("0039",))
        else:
            connection.execute(
                f'CREATE VIEW "{name}" AS SELECT version_num FROM biological_observations'
            )
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0039",)
    original = database.read_bytes()
    canonical = name == "alembic_version" and kind == "table"
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == (0 if canonical else 2), result.stderr
        report = json.loads(result.stdout)
        assert ("noncanonical_alembic_version_object" in report["warnings"]) is not canonical
        assert report["revision_rows"] == (["0039"] if canonical else [])
        assert report["canonical_alembic_stamp_constraints"] is canonical
        assert report["upgrade_authorized"] is False
        assert "private coral observation" not in result.stdout + result.stderr
        assert database.read_bytes() == original


@pytest.mark.parametrize("lineage", ["scientific", "qc"])
@pytest.mark.parametrize(
    "revision",
    ["0039", "0042", "0043", "9999", "external-head", "53ba400993db", "0000", "0037"],
)
def test_revision_must_belong_to_detected_schema_lineage(
    tmp_path: Path, lineage: str, revision: str
) -> None:
    database = tmp_path / "lineage-head.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        tables = (
            (
                "scientific_records",
                "environmental_cache_entries",
                "computed_metric_definitions",
                "computed_metric_results",
            )
            if lineage == "scientific"
            else ("review_queue_item_events",)
        )
        for table in tables:
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, note TEXT)')
            connection.execute(f'INSERT INTO "{table}" VALUES (1, ?)', ("private coral record",))
        if lineage == "scientific" and revision == "0042":
            _add_0041_aggregate_columns(connection)
            for table in (
                "environmental_event_definitions",
                "environmental_analysis_definitions",
                "environmental_analysis_results",
            ):
                connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    unsupported = revision not in {"0039", "0037"} and not (
        lineage == "scientific" and revision == "0042"
    )
    original = database.read_bytes()
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fail-on-warning", str(database)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == (2 if unsupported or revision == "0037" else 0), result.stderr
        report = json.loads(result.stdout)
        assert ("revision_not_supported_for_schema_lineage" in report["warnings"]) is unsupported
        assert report["lineage_hint"] == lineage
        assert report["revision_rows"] == [revision]
        assert report["upgrade_authorized"] is False
        assert "private coral record" not in result.stdout + result.stderr
        assert database.read_bytes() == original


@pytest.mark.parametrize("revision", ["0039", "0040", "0041", "0042"])
@pytest.mark.parametrize(
    ("variant", "mismatch"),
    [
        ("valid", None),
        ("unit_type", "computed_metric_definitions"),
        ("formula_nullable", "computed_metric_definitions"),
        ("workflow_cascade", "computed_metric_results"),
        ("missing_unique", "computed_metric_results"),
        ("unique_renamed", "computed_metric_results"),
        ("unique_unnamed", "computed_metric_results"),
        ("missing_index", "computed_metric_results"),
        ("result_trigger", "computed_metric_results"),
        ("duplicate_workflow_fk", "computed_metric_results"),
    ],
)
def test_computed_metric_structural_contracts(
    tmp_path: Path, revision: str, variant: str, mismatch: str | None
) -> None:
    database = tmp_path / "metric-contract.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for parent in ("projects", "workflow_runs", "workflow_node_runs"):
            connection.execute(f'CREATE TABLE "{parent}" (id VARCHAR(36) PRIMARY KEY)')
        _create_0039_metric_pair(connection, variant)
        if revision in {"0041", "0042"}:
            _add_0041_aggregate_columns(connection)
        connection.execute("INSERT INTO projects VALUES ('project-1')")
        connection.execute(
            "INSERT INTO computed_metric_definitions "
            "(id, project_id, name, expression, formula_version, input_spec_json, output_unit, "
            "definition_sha256, created_at) VALUES "
            "('def-1', 'project-1', 'PRIVATE_FORMULA', 'x', 'v1', '{}', 'mm', 'hash', '2026-11-24')"
        )
        connection.execute(
            "INSERT INTO computed_metric_results "
            "(id, project_id, definition_id, observed_at, payload_json, "
            "content_sha256, created_at) "
            "VALUES ('result-1', 'project-1', 'def-1', '2026-11-24', "
            "'PRIVATE_METRIC_VALUE', 'hash', '2026-11-24')"
        )
    original = database.read_bytes()
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--verify-structural-contracts", str(database)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        report = json.loads(completed.stdout)
        assert report["lineage_hint"] == "scientific"
        assert report["upgrade_authorized"] is False
        for table in ("computed_metric_definitions", "computed_metric_results"):
            assert report["structural_contracts"][table] == (
                "mismatch" if table == mismatch else "matches"
            )
            assert (f"lineage_table_contract_mismatch_{table}" in report["warnings"]) == (
                table == mismatch
            )
            assert report["inventory"][table]["rows"] == 1
        for private in ("PRIVATE_FORMULA", "PRIVATE_METRIC_VALUE", "PRIVATE_TRIGGER_BODY"):
            assert private not in completed.stdout + completed.stderr
        assert database.read_bytes() == original
