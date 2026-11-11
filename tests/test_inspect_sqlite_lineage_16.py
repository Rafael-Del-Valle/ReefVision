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
