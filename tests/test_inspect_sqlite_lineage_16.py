"""Read-only 1.1/1.6 lineage evidence inspector regressions (stdlib-only)."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_sqlite_lineage_16.py"
spec = importlib.util.spec_from_file_location("inspect_sqlite_lineage_16", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_ambiguous_0038_is_not_classified_from_stamp(tmp_path: Path) -> None:
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('0038')")
        db.execute("CREATE TABLE review_queue_item_events (id TEXT PRIMARY KEY)")
    before = path.read_bytes()
    evidence = module.inspect(path)
    assert evidence["alembic_stamps"] == ["0038"]
    assert evidence["tables"]["review_queue_item_events"]["present"]
    assert not evidence["tables"]["scientific_records"]["present"]
    assert evidence["classification"] == "requires_researcher_review"
    assert evidence["quick_check"] == "ok"
    assert evidence["foreign_key_violation_count"] == 0
    assert evidence["foreign_key_violations"] == []
    assert before == path.read_bytes()


def test_missing_file_never_creates_database(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        module.inspect(path)
    assert not path.exists()


def test_foreign_key_violations_are_reported_without_repair(tmp_path: Path) -> None:
    path = tmp_path / "broken_research.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY)")
        db.execute(
            "CREATE TABLE review_queue_item_events ("
            "id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id))"
        )
        db.execute("INSERT INTO review_queue_item_events VALUES (1, 999)")
    before = path.read_bytes()
    evidence = module.inspect(path)
    assert evidence["foreign_key_violation_count"] == 1
    assert evidence["foreign_key_violations"] == [
        {"table": "review_queue_item_events", "rowid": 1, "parent": "projects", "fkid": 0}
    ]
    assert evidence["classification"] == "requires_researcher_review"
    assert evidence["tables"]["review_queue_item_events"]["foreign_keys"][0]["table"] == "projects"
    assert path.read_bytes() == before


def test_wal_uncheckpointed_schema_is_visible_without_changing_database(tmp_path: Path) -> None:
    path = tmp_path / "wal_research.sqlite"
    with sqlite3.connect(path) as setup:
        setup.execute("PRAGMA journal_mode=WAL")
        setup.execute("PRAGMA wal_autocheckpoint=0")
        setup.execute("CREATE TABLE alembic_version (version_num TEXT)")
    writer = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO alembic_version VALUES ('0038')")
        writer.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY)")
        writer.commit()
        before = path.read_bytes()
        evidence = module.inspect(path)
        assert evidence["alembic_stamps"] == ["0038"]
        assert evidence["tables"]["scientific_records"]["present"]
        assert evidence["classification"] == "requires_researcher_review"
        assert path.read_bytes() == before
    finally:
        writer.close()


def test_multiple_foreign_key_violations_have_stable_order(tmp_path: Path) -> None:
    path = tmp_path / "multiple_orphans.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY)")
        db.execute(
            "CREATE TABLE review_queue_item_events ("
            "id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id))"
        )
        db.execute(
            "CREATE TABLE review_queue_bulk_requests ("
            "id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id))"
        )
        db.execute("INSERT INTO review_queue_item_events VALUES (8, 800)")
        db.execute("INSERT INTO review_queue_bulk_requests VALUES (2, 200)")
    before = path.read_bytes()
    first = module.inspect(path)
    second = module.inspect(path)
    assert first["foreign_key_violation_count"] == 2
    assert first["foreign_key_violations"] == second["foreign_key_violations"]
    assert first["foreign_key_violations"] == [
        {"table": "review_queue_bulk_requests", "rowid": 2, "parent": "projects", "fkid": 0},
        {"table": "review_queue_item_events", "rowid": 8, "parent": "projects", "fkid": 0},
    ]
    assert path.read_bytes() == before


def test_concurrent_wal_commit_does_not_mix_lineage_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writer committing mid-inspection must not alter the reader's snapshot."""
    path = tmp_path / "concurrent.sqlite"
    with sqlite3.connect(path) as setup:
        setup.execute("PRAGMA journal_mode=WAL")
        setup.execute("CREATE TABLE alembic_version (version_num TEXT)")
        setup.execute("INSERT INTO alembic_version VALUES ('0038')")
    writer = sqlite3.connect(path)
    original_connect = sqlite3.connect
    committed = False

    class InterleavedConnection:
        def __init__(self, actual: sqlite3.Connection) -> None:
            self.actual = actual

        def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
            nonlocal committed
            if sql == "PRAGMA foreign_key_check" and not committed:
                writer.execute("INSERT INTO alembic_version VALUES ('0039')")
                writer.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY)")
                writer.commit()
                committed = True
            return self.actual.execute(sql, *args)

        def close(self) -> None:
            self.actual.close()

    def connect(*args: object, **kwargs: object) -> InterleavedConnection:
        return InterleavedConnection(original_connect(*args, **kwargs))

    try:
        monkeypatch.setattr(module.sqlite3, "connect", connect)
        evidence = module.inspect(path)
        assert committed
        assert evidence["alembic_stamps"] == ["0038"]
        assert not evidence["tables"]["scientific_records"]["present"]
        assert evidence["classification"] == "requires_researcher_review"
    finally:
        writer.close()


def test_schema_fingerprint_is_stable_and_distinguishes_colliding_stamps(tmp_path: Path) -> None:
    """Identical revision stamps cannot stand in for structural lineage evidence."""
    first_path = tmp_path / "scientific.sqlite"
    second_path = tmp_path / "qc.sqlite"
    for path, ddl in (
        (first_path, "CREATE TABLE scientific_records (id INTEGER PRIMARY KEY)"),
        (second_path, "CREATE TABLE review_queue_item_events (id INTEGER PRIMARY KEY)"),
    ):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE alembic_version (version_num TEXT)")
            db.execute("INSERT INTO alembic_version VALUES ('0038')")
            db.execute(ddl)
    first_bytes, second_bytes = first_path.read_bytes(), second_path.read_bytes()
    scientific = module.inspect(first_path)
    qc = module.inspect(second_path)
    assert scientific["alembic_stamps"] == qc["alembic_stamps"] == ["0038"]
    assert len(scientific["schema_sha256"]) == len(qc["schema_sha256"]) == 64
    assert scientific["schema_sha256"] != qc["schema_sha256"]
    assert scientific["schema_sha256"] == module.inspect(first_path)["schema_sha256"]
    assert qc["schema_sha256"] == module.inspect(second_path)["schema_sha256"]
    assert first_path.read_bytes() == first_bytes
    assert second_path.read_bytes() == second_bytes


def test_schema_fingerprint_includes_indexes_but_excludes_record_changes(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, value TEXT)")
    baseline = module.inspect(path)["schema_sha256"]
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO scientific_records VALUES (1, 'sensitive research observation')")
    assert module.inspect(path)["schema_sha256"] == baseline
    with sqlite3.connect(path) as db:
        db.execute("CREATE INDEX idx_scientific_value ON scientific_records(value)")
    assert module.inspect(path)["schema_sha256"] != baseline

def test_sqlite_header_metadata_is_evidence_not_lineage_classification(tmp_path: Path) -> None:
    """Capture non-default header fields without trusting them as migrations."""
    path = tmp_path / "header.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA application_id=12345")
        db.execute("PRAGMA user_version=47")
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('0038')")
    before = path.read_bytes()
    evidence = module.inspect(path)
    assert evidence["sqlite_header"]["application_id"] == 12345
    assert evidence["sqlite_header"]["user_version"] == 47
    assert evidence["sqlite_header"]["schema_version"] >= 1
    assert evidence["classification"] == "requires_researcher_review"
    assert path.read_bytes() == before


def test_malformed_foreign_key_parent_is_reported_not_misclassified(tmp_path: Path) -> None:
    """An invalid parent key must not be reported as zero FK violations."""
    path = tmp_path / "malformed_fk.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE parent (id INTEGER)")
        db.execute("CREATE TABLE review_queue_item_events ("
                   "id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))")
        db.execute("INSERT INTO review_queue_item_events VALUES (1, 7)")
    before = path.read_bytes()
    evidence = module.inspect(path)
    assert evidence["quick_check"] == "ok"
    assert evidence["foreign_key_violation_count"] is None
    assert "foreign key mismatch" in evidence["foreign_key_check_error"]
    assert evidence["foreign_key_violations"] == []
    assert evidence["classification"] == "requires_researcher_review"
    assert path.read_bytes() == before


def test_valid_foreign_keys_have_explicit_success_evidence(tmp_path: Path) -> None:
    path = tmp_path / "valid_fk.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE review_queue_item_events ("
                   "id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))")
        db.execute("INSERT INTO parent VALUES (7)")
        db.execute("INSERT INTO review_queue_item_events VALUES (1, 7)")
    evidence = module.inspect(path)
    assert evidence["foreign_key_check_error"] is None
    assert evidence["foreign_key_violation_count"] == 0
    assert evidence["foreign_key_violations"] == []

def test_malformed_alembic_table_reports_uncertain_stamp_without_writes(tmp_path: Path) -> None:
    """A partial revision table must not suppress schema/FK evidence or imply success."""
    path = tmp_path / "malformed_alembic.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (wrong_column TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('0038')")
        db.execute("CREATE TABLE review_queue_item_events (id INTEGER PRIMARY KEY)")
    before = path.read_bytes()
    evidence = module.inspect(path)
    assert evidence["alembic_stamps"] == []
    assert "no such column" in evidence["alembic_stamp_error"]
    assert evidence["tables"]["review_queue_item_events"]["present"]
    assert evidence["classification"] == "requires_researcher_review"
    assert evidence["foreign_key_violation_count"] == 0
    assert path.read_bytes() == before


def test_valid_alembic_table_has_no_stamp_error(tmp_path: Path) -> None:
    path = tmp_path / "valid_alembic.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('0041')")
    evidence = module.inspect(path)
    assert evidence["alembic_stamps"] == ["0041"]
    assert evidence["alembic_stamp_error"] is None
    assert evidence["classification"] == "requires_researcher_review"


def test_quick_check_retains_all_diagnostics_without_modifying_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A damaged database may yield more than one quick_check diagnostic."""
    path = tmp_path / "multiple_checks.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY)")
    before = path.read_bytes()
    original_connect = sqlite3.connect

    class CheckConnection:
        def __init__(self, actual: sqlite3.Connection) -> None:
            self.actual = actual

        def execute(self, sql: str, *args: object) -> object:
            if sql == "PRAGMA quick_check":
                return iter([("first integrity problem",), ("second integrity problem",)])
            return self.actual.execute(sql, *args)

        def close(self) -> None:
            self.actual.close()

    def connect(*args: object, **kwargs: object) -> CheckConnection:
        return CheckConnection(original_connect(*args, **kwargs))

    monkeypatch.setattr(module.sqlite3, "connect", connect)
    evidence = module.inspect(path)
    assert evidence["quick_check"] == "first integrity problem"
    assert evidence["quick_check_details"] == [
        "first integrity problem", "second integrity problem"
    ]
    assert evidence["classification"] == "requires_researcher_review"
    assert path.read_bytes() == before


def test_healthy_quick_check_details_are_explicit(tmp_path: Path) -> None:
    path = tmp_path / "healthy.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY)")
    evidence = module.inspect(path)
    assert evidence["quick_check"] == "ok"
    assert evidence["quick_check_details"] == ["ok"]


def test_sqlite_prefix_wildcard_does_not_hide_user_schema(tmp_path: Path) -> None:
    """Only literal sqlite_ names are internal; sqliteX is a valid user prefix."""
    path = tmp_path / "prefix.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE ordinary_observations (id INTEGER PRIMARY KEY)")
    baseline = module.inspect(path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sqliteXobservations (id INTEGER PRIMARY KEY)")
    before = path.read_bytes()
    evidence = module.inspect(path)
    assert evidence["schema_sha256"] != baseline["schema_sha256"]
    assert evidence["classification"] == "requires_researcher_review"
    assert path.read_bytes() == before


def test_generated_columns_are_visible_in_extended_lineage_evidence(tmp_path: Path) -> None:
    """SQLite table_info omits generated columns; xinfo must retain their provenance."""
    path = tmp_path / "generated_metrics.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE scientific_records ("
            "id INTEGER PRIMARY KEY, length_mm REAL, "
            "length_cm REAL GENERATED ALWAYS AS (length_mm / 10.0) STORED)"
        )
    before = path.read_bytes()
    evidence = module.inspect(path)
    table = evidence["tables"]["scientific_records"]
    assert [column["name"] for column in table["columns"]] == ["id", "length_mm"]
    assert [column["name"] for column in table["extended_columns"]] == [
        "id", "length_mm", "length_cm"
    ]
    assert table["extended_columns"][2]["hidden"] == 3
    assert table["extended_columns"][2]["type"] == "REAL"
    assert evidence["classification"] == "requires_researcher_review"
    assert path.read_bytes() == before


def test_ordinary_columns_keep_legacy_and_extended_metadata(tmp_path: Path) -> None:
    path = tmp_path / "ordinary.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE review_queue_item_events (id INTEGER PRIMARY KEY)")
    evidence = module.inspect(path)
    table = evidence["tables"]["review_queue_item_events"]
    assert [column["name"] for column in table["columns"]] == ["id"]
    assert [column["name"] for column in table["extended_columns"]] == ["id"]
    assert table["extended_columns"][0]["hidden"] == 0


def test_cli_integrity_gate_preserves_json_and_database(tmp_path: Path) -> None:
    """An opt-in machine gate must not mislabel lineage or change scientific bytes."""
    import json
    import subprocess
    import sys

    path = tmp_path / "cli_gate.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('0038')")
        db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        db.execute(
            "CREATE TABLE review_queue_item_events ("
            "id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
        )
        db.execute("INSERT INTO review_queue_item_events VALUES (1, 99)")
    before = path.read_bytes()
    command = [sys.executable, str(SCRIPT), str(path)]
    default = subprocess.run(command, capture_output=True, text=True, check=False)
    gated = subprocess.run(
        command + ["--fail-on-integrity-error"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert default.returncode == 0
    assert gated.returncode == 2
    assert not gated.stderr
    evidence = json.loads(gated.stdout)
    assert evidence == json.loads(default.stdout)
    assert evidence["foreign_key_violation_count"] == 1
    assert evidence["classification"] == "requires_researcher_review"
    assert path.read_bytes() == before


def test_cli_integrity_gate_does_not_treat_ambiguous_stamp_as_integrity_error(
    tmp_path: Path,
) -> None:
    """A healthy SQLite database with 0038 still requires human lineage review."""
    import json
    import subprocess
    import sys

    path = tmp_path / "healthy_ambiguous.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('0038')")
    before = path.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path), "--fail-on-integrity-error"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["classification"] == "requires_researcher_review"
    assert path.read_bytes() == before


def test_cli_integrity_gate_rejects_malformed_alembic_metadata(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    path = tmp_path / "bad_stamp.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (wrong_column TEXT)")
    before = path.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-integrity-error", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "no such column" in json.loads(result.stdout)["alembic_stamp_error"]
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("values", "expected_error"),
    [
        ([], "expected_exactly_one_revision_row"),
        (["0037", "0038"], "expected_exactly_one_revision_row"),
        ([" 0038"], "invalid_revision_marker_type_or_value"),
        (["0038\\n"], "invalid_revision_marker_type_or_value"),
        ([None], "invalid_revision_marker_type_or_value"),
        ([38], "invalid_revision_marker_type_or_value"),
        ([b"\\x00\\xff"], "invalid_revision_marker_type_or_value"),
    ],
)
def test_lineage_cli_rejects_invalid_revision_values_without_mutating_science(
    tmp_path: Path, values: list[object], expected_error: str
) -> None:
    """Malformed Alembic values must be JSON-safe and block the opt-in integrity gate."""
    import json
    import subprocess
    import sys

    path = tmp_path / "invalid_stamps.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num)")
        db.executemany("INSERT INTO alembic_version VALUES (?)", [(v,) for v in values])
        db.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, note TEXT)")
        db.execute("INSERT INTO scientific_records VALUES (1, 'preserve')")
    before = path.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fail-on-integrity-error", str(path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["alembic_stamp_validation_error"] == expected_error
    assert report["classification"] == "requires_researcher_review"
    assert report["tables"]["scientific_records"]["present"] is True
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT note FROM scientific_records").fetchone() == ("preserve",)


def test_schema_object_inventory_is_stable_and_excludes_observation_values(tmp_path: Path) -> None:
    """Migration review needs named objects without leaking scientific rows or DDL."""
    path = tmp_path / "objects.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, secret TEXT)")
        db.execute("CREATE INDEX scientific_records_secret_idx ON scientific_records(secret)")
        db.execute("CREATE VIEW scientific_record_ids AS SELECT id FROM scientific_records")
        db.execute(
            "CREATE TRIGGER scientific_record_no_delete BEFORE DELETE ON scientific_records "
            "BEGIN SELECT RAISE(ABORT, 'protected'); END"
        )
        db.execute("INSERT INTO scientific_records VALUES (1, 'sensitive specimen location')")
    before = path.read_bytes()
    first = module.inspect(path)
    second = module.inspect(path)
    objects = first["schema_objects"]
    assert objects == second["schema_objects"]
    assert {item["name"] for item in objects} == {
        "scientific_records",
        "scientific_records_secret_idx",
        "scientific_record_ids",
        "scientific_record_no_delete",
    }
    assert {item["type"] for item in objects} == {"table", "index", "view", "trigger"}
    assert all(set(item) == {"type", "name", "table"} for item in objects)
    assert "sensitive specimen location" not in str(objects)
    assert first["classification"] == "requires_researcher_review"
    assert path.read_bytes() == before


def test_schema_comparison_cli_detects_same_name_changed_ddl_without_writes(
    tmp_path: Path,
) -> None:
    """Equal object names do not imply equal migration topology."""
    import json
    import subprocess
    import sys

    current = tmp_path / "current.sqlite"
    reference = tmp_path / "reference.sqlite"
    with sqlite3.connect(current) as db:
        db.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, depth_m REAL)")
        db.execute("INSERT INTO scientific_records VALUES (1, 45.0)")
    with sqlite3.connect(reference) as db:
        db.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, depth_cm REAL)")
        db.execute("INSERT INTO scientific_records VALUES (1, 4500.0)")
    original = (current.read_bytes(), reference.read_bytes())
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), str(current), "--compare-to",
            str(reference), "--fail-on-schema-drift",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    comparison = report["schema_comparison"]
    assert comparison["matches"] is False
    assert comparison["only_in_database"] == []
    assert comparison["only_in_reference"] == []
    assert comparison["requires_researcher_review"] is True
    assert report["classification"] == "requires_researcher_review"
    assert "45.0" not in result.stdout
    assert "4500.0" not in result.stdout
    assert (current.read_bytes(), reference.read_bytes()) == original


def test_schema_comparison_cli_accepts_equal_structures_with_different_rows(
    tmp_path: Path,
) -> None:
    import json
    import subprocess
    import sys

    current = tmp_path / "current.sqlite"
    reference = tmp_path / "reference.sqlite"
    for path, value in ((current, "secret coral A"), (reference, "secret coral B")):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, note TEXT)")
            db.execute("INSERT INTO scientific_records VALUES (1, ?)", (value,))
    original = (current.read_bytes(), reference.read_bytes())
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), str(current), "--compare-to",
            str(reference), "--fail-on-schema-drift",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_comparison"]["matches"] is True
    assert report["schema_comparison"]["only_in_database"] == []
    assert report["schema_comparison"]["only_in_reference"] == []
    assert "secret coral" not in result.stdout
    assert (current.read_bytes(), reference.read_bytes()) == original


@pytest.mark.parametrize("invalid_reference", [True, False])
def test_comparison_integrity_gate_checks_both_inputs(
    tmp_path: Path, invalid_reference: bool
) -> None:
    """Matching DDL cannot hide orphaned foreign keys in either input."""
    import json
    import subprocess
    import sys

    current = tmp_path / "current.sqlite"
    reference = tmp_path / "reference.sqlite"
    for path in (current, reference):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            db.execute(
                "CREATE TABLE review_queue_item_events ("
                "id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
            )
            db.execute("INSERT INTO parent VALUES (1)")
            db.execute("INSERT INTO review_queue_item_events VALUES (1, 1)")
    damaged = reference if invalid_reference else current
    with sqlite3.connect(damaged) as db:
        db.execute("UPDATE review_queue_item_events SET parent_id=99")
    original = (current.read_bytes(), reference.read_bytes())
    command = [
        sys.executable, str(SCRIPT), str(current), "--compare-to", str(reference),
        "--fail-on-integrity-error",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_comparison"]["matches"] is True
    assert report["schema_comparison"]["reference_integrity"][
        "foreign_key_violation_count"
    ] == (1 if invalid_reference else 0)
    assert report["foreign_key_violation_count"] == (0 if invalid_reference else 1)
    assert report["classification"] == "requires_researcher_review"
    assert (current.read_bytes(), reference.read_bytes()) == original


def test_comparison_integrity_gate_reports_malformed_reference_stamp(
    tmp_path: Path,
) -> None:
    import json
    import subprocess
    import sys

    current = tmp_path / "current.sqlite"
    reference = tmp_path / "reference.sqlite"
    for path in (current, reference):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE alembic_version (version_num TEXT)")
            db.execute("INSERT INTO alembic_version VALUES ('0038')")
    with sqlite3.connect(reference) as db:
        db.execute("DELETE FROM alembic_version")
    original = (current.read_bytes(), reference.read_bytes())
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), str(current), "--compare-to",
            str(reference), "--fail-on-integrity-error",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_comparison"]["matches"] is True
    assert report["schema_comparison"]["reference_integrity"][
        "alembic_stamp_validation_error"
    ] == "expected_exactly_one_revision_row"
    assert (current.read_bytes(), reference.read_bytes()) == original


@pytest.mark.parametrize(
    ("current_stamp", "reference_stamp", "expected_code"),
    [("0038", "0038", 0), ("0038", "0039", 2)],
)
def test_revision_comparison_gate_detects_equal_schema_different_lineage(
    tmp_path: Path, current_stamp: str, reference_stamp: str, expected_code: int
) -> None:
    """Identical DDL is insufficient evidence of equal migration histories."""
    import json
    import subprocess
    import sys

    current = tmp_path / "current.sqlite"
    reference = tmp_path / "reference.sqlite"
    for path, stamp in ((current, current_stamp), (reference, reference_stamp)):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE alembic_version (version_num TEXT)")
            db.execute("INSERT INTO alembic_version VALUES (?)", (stamp,))
            db.execute("CREATE TABLE scientific_records (id INTEGER, note TEXT)")
            db.execute("INSERT INTO scientific_records VALUES (1, 'private observation')")
    before = (current.read_bytes(), reference.read_bytes())
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), str(current), "--compare-to",
            str(reference), "--fail-on-revision-mismatch",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == expected_code, result.stderr
    report = json.loads(result.stdout)
    comparison = report["schema_comparison"]
    assert comparison["matches"] is True
    assert comparison["revision_markers_match"] is (expected_code == 0)
    assert comparison["requires_researcher_review"] is True
    assert "private observation" not in result.stdout
    assert (current.read_bytes(), reference.read_bytes()) == before


def test_revision_comparison_gate_rejects_malformed_reference_stamp(
    tmp_path: Path,
) -> None:
    import json
    import subprocess
    import sys

    current = tmp_path / "current.sqlite"
    reference = tmp_path / "reference.sqlite"
    for path in (current, reference):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE alembic_version (version_num TEXT)")
            db.execute("INSERT INTO alembic_version VALUES ('0038')")
    with sqlite3.connect(reference) as db:
        db.execute("DELETE FROM alembic_version")
    before = (current.read_bytes(), reference.read_bytes())
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), str(current), "--compare-to",
            str(reference), "--fail-on-revision-mismatch",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2, result.stderr
    assert (
        json.loads(result.stdout)["schema_comparison"]["revision_markers_match"] is False
    )
    assert (current.read_bytes(), reference.read_bytes()) == before
