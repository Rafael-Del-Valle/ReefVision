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
