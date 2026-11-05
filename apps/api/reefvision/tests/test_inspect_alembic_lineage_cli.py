"""Regression tests for the standalone read-only migration lineage inventory."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "inspect-alembic-lineage.py"
SPEC = importlib.util.spec_from_file_location("inspect_alembic_lineage", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize(
    ("tables", "expected"),
    [
        ([], "unknown"),
        (["scientific_records"], "scientific"),
        (["review_queue_item_events"], "qc"),
        (["scientific_records", "review_queue_item_events"], "ambiguous"),
    ],
)
def test_inventory_is_read_only_and_never_authorizes_upgrade(tmp_path, tables, expected):
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('0038')")
        for table in tables:
            db.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, evidence TEXT)')
            db.execute(f'INSERT INTO "{table}" (evidence) VALUES (?)', ("coral sentinel",))
        db.commit()
    before = path.read_bytes()
    result = module.inspect(path)
    assert result["lineage_hint"] == expected
    assert result["revision_rows"] == ["0038"]
    assert result["upgrade_authorized"] is False
    for table in tables:
        assert result["inventory"][table]["rows"] == 1
        assert result["inventory"][table]["columns"] == ["id", "evidence"]
    assert path.read_bytes() == before


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError, match="does not exist"):
        module.inspect(path)
    assert not path.exists()
