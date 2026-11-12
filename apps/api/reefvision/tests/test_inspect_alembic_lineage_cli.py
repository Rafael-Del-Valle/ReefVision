"""Regression tests for the standalone read-only migration lineage inventory."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "inspect-alembic-lineage.py"
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


@pytest.mark.parametrize(
    ("revision_rows", "tables", "expected_warning"),
    [
        ([], [], "invalid_revision_marker_count_or_value"),
        (["0038", "0038"], [], "invalid_revision_marker_count_or_value"),
        ([""], [], "invalid_revision_marker_count_or_value"),
        (
            ["0038"],
            ["scientific_records", "review_queue_item_events"],
            "mixed_scientific_and_qc_lineage",
        ),
        (["0038"], ["scientific_records"], "revision_0038_requires_schema_lineage_reconciliation"),
        (["0037"], [], "unrecognized_schema_lineage"),
    ],
)
def test_lineage_warnings_are_read_only(tmp_path, revision_rows, tables, expected_warning):
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.executemany("INSERT INTO alembic_version VALUES (?)", [(row,) for row in revision_rows])
        for table in tables:
            db.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        db.commit()
    before = path.read_bytes()
    result = module.inspect(path)
    assert expected_warning in result["warnings"]
    assert result["upgrade_authorized"] is False
    assert path.read_bytes() == before


def test_missing_revision_table_is_explicitly_reported(tmp_path):
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY)")
        db.commit()
    before = path.read_bytes()
    result = module.inspect(path)
    assert "missing_alembic_version_table" in result["warnings"]
    assert result["lineage_hint"] == "scientific"
    assert result["upgrade_authorized"] is False
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("tables", "expected_warnings"),
    [
        (["scientific_records"], {"incomplete_scientific_schema_family"}),
        (["review_queue_item_events"], {"incomplete_qc_schema_family"}),
        (
            ["scientific_records", "review_queue_item_events"],
            {
                "incomplete_scientific_schema_family",
                "incomplete_qc_schema_family",
                "mixed_scientific_and_qc_lineage",
            },
        ),
        (
            [
                "scientific_records",
                "environmental_cache_entries",
                "computed_metric_definitions",
                "computed_metric_results",
            ],
            set(),
        ),
        (["review_queue_item_events", "review_queue_bulk_requests"], set()),
    ],
)
def test_partial_migration_families_never_imply_safe_upgrade(tmp_path, tables, expected_warnings):
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
    assert expected_warnings.issubset(set(result["warnings"]))
    for family in ("scientific", "qc"):
        warning = f"incomplete_{family}_schema_family"
        assert (warning in result["warnings"]) == (warning in expected_warnings)
    assert result["upgrade_authorized"] is False
    assert all(result["inventory"][table]["rows"] == 1 for table in tables)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("revision_value", "expected_warning"),
    [
        (b"0038", "invalid_revision_marker_count_or_value"),
        (38, "invalid_revision_marker_count_or_value"),
        (" 0038", "invalid_revision_marker_count_or_value"),
        ("0038\n", "invalid_revision_marker_count_or_value"),
    ],
)
def test_noncanonical_revision_marker_is_json_safe_and_read_only(
    tmp_path, revision_value, expected_warning
):
    """A corrupted revision stamp must not crash JSON reporting or authorize migration."""
    import json

    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num)")
        db.execute("INSERT INTO alembic_version VALUES (?)", (revision_value,))
        db.commit()
    before = path.read_bytes()
    result = module.inspect(path)
    assert expected_warning in result["warnings"]
    assert result["upgrade_authorized"] is False
    assert json.loads(json.dumps(result))["upgrade_authorized"] is False
    assert path.read_bytes() == before


def test_foreign_key_violations_are_reported_without_mutation(tmp_path):
    """Orphaned scientific references must be visible even when SQLite integrity passes."""
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('0038')")
        db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        db.execute(
            "CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, parent_id INTEGER "
            "REFERENCES parent(id))"
        )
        db.execute("INSERT INTO scientific_records VALUES (1, 999)")
        db.commit()
    before = path.read_bytes()
    result = module.inspect(path)
    assert result["sqlite_foreign_key_violations"] == 1
    assert "sqlite_foreign_key_violations" in result["warnings"]
    assert result["upgrade_authorized"] is False
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("stamp_definition", "canonical"),
    [
        ("version_num VARCHAR(32) NOT NULL PRIMARY KEY", True),
        ("version_num TEXT NOT NULL PRIMARY KEY", True),
        ("version_num TEXT", False),
        ("version_num TEXT PRIMARY KEY", False),
        ("version_num TEXT NOT NULL", False),
        ("version_num TEXT NOT NULL PRIMARY KEY, foreign_stamp TEXT", False),
    ],
)
def test_alembic_stamp_constraints_are_diagnosed_without_mutation(
    tmp_path, stamp_definition, canonical
):
    """An identical revision is not proof of a canonical Alembic stamp."""
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE alembic_version ({stamp_definition})")
        db.execute("INSERT INTO alembic_version (version_num) VALUES ('0038')")
        db.commit()
    before = path.read_bytes()
    result = module.inspect(path)
    assert result["canonical_alembic_stamp_constraints"] is canonical
    assert ("noncanonical_alembic_stamp_constraints" in result["warnings"]) is not canonical
    assert result["revision_rows"] == ["0038"]
    assert result["upgrade_authorized"] is False
    assert path.read_bytes() == before
