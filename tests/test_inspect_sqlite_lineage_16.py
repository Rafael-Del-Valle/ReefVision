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
