"""Non-destructive, source-projection preservation checks for 1.1/1.6 convergence."""

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify-research-row-preservation-16.py"


def _seed(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0038')")
        for table in (
            "scientific_records",
            "review_queue_item_events",
            "class_visibility_preferences",
            "workflow_graph_records",
            "annotations",
        ):
            connection.execute(
                f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY, payload BLOB NOT NULL, note TEXT)'
            )
            connection.execute(
                f'INSERT INTO "{table}" VALUES (?, ?, ?)',
                ("z", b"\x00\xff", "coral \u03b1; private record"),
            )
            connection.execute(
                f'INSERT INTO "{table}" VALUES (?, ?, ?)',
                ("a", b"\x10\x11", None),
            )


def _run(before: Path, after: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--before", str(before), "--after", str(after)],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


@pytest.mark.parametrize(
    ("table", "mutation", "expected"),
    [
        (
            "scientific_records",
            "UPDATE scientific_records SET note = 'forged' WHERE id = 'z'",
            "changed_records",
        ),
        (
            "review_queue_item_events",
            "DELETE FROM review_queue_item_events WHERE id = 'a'",
            "changed_records",
        ),
        (
            "workflow_graph_records",
            "INSERT INTO workflow_graph_records VALUES ('new', X'00', NULL)",
            "changed_records",
        ),
        (
            "class_visibility_preferences",
            "ALTER TABLE class_visibility_preferences DROP COLUMN note",
            "removed_columns",
        ),
        ("annotations", "DROP TABLE annotations", "removed_table"),
    ],
)
def test_detects_modified_science_qc_class_and_workflow_evidence(
    tmp_path: Path, table: str, mutation: str, expected: str
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    original = before.read_bytes()
    with sqlite3.connect(after) as connection:
        connection.execute(mutation)
    modified = after.read_bytes()
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert any(item["table"] == table and item["status"] == expected for item in report["tables"])
    assert "coral \u03b1; private record" not in json.dumps(report)
    assert before.read_bytes() == original
    assert after.read_bytes() == modified


def test_additive_schema_and_new_qc_table_preserve_original_record_projection(
    tmp_path: Path,
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    old_bytes = before.read_bytes()
    with sqlite3.connect(after) as connection:
        connection.execute("ALTER TABLE scientific_records ADD COLUMN new_science TEXT")
        connection.execute("CREATE TABLE review_queue_bulk_requests (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO review_queue_bulk_requests VALUES ('new')")
        connection.execute("UPDATE alembic_version SET version_num = '0041'")
    new_bytes = after.read_bytes()
    code, report = _run(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["protected_tables_examined"] == 5
    assert report["requires_researcher_approval"] is True
    assert report["upgrade_authorized"] is False
    assert not report["problems"]
    assert all(entry["status"] in {"preserved", "not_in_baseline"} for entry in report["tables"])
    assert before.read_bytes() == old_bytes
    assert after.read_bytes() == new_bytes


@pytest.mark.parametrize("storage", ["VIRTUAL", "STORED"])
@pytest.mark.parametrize("candidate", ["changed_expression", "removed_column"])
def test_generated_scientific_column_preserved(
    tmp_path: Path, storage: str, candidate: str
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"

    def create(path: Path, expression: str | None) -> None:
        generated = (
            f", length_mm REAL GENERATED ALWAYS AS ({expression}) {storage}"
            if expression is not None
            else ""
        )
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE scientific_records "
                f"(id TEXT PRIMARY KEY, raw_length_mm REAL NOT NULL{generated})"
            )
            connection.execute(
                "INSERT INTO scientific_records (id, raw_length_mm) VALUES (?, ?)",
                ("coral-1", 3.5),
            )

    create(before, "raw_length_mm * 2.0")
    create(
        after,
        "raw_length_mm * 3.0" if candidate == "changed_expression" else None,
    )
    original = before.read_bytes()
    upgraded = after.read_bytes()
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    expected = "changed_records" if candidate == "changed_expression" else "removed_columns"
    assert any(
        item["table"] == "scientific_records" and item["status"] == expected
        for item in report["tables"]
    )
    assert report["upgrade_authorized"] is False
    assert "coral-1" not in json.dumps(report)
    assert before.read_bytes() == original
    assert after.read_bytes() == upgraded


@pytest.mark.parametrize("storage", ["VIRTUAL", "STORED"])
def test_new_generated_column_does_not_modify_original_science(
    tmp_path: Path, storage: str
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    with sqlite3.connect(before) as connection:
        connection.execute(
            "CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, raw_length_mm REAL)"
        )
        connection.execute("INSERT INTO scientific_records VALUES (1, 3.5)")
    with sqlite3.connect(after) as connection:
        connection.execute(
            "CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, raw_length_mm REAL, "
            f"length_mm REAL GENERATED ALWAYS AS (raw_length_mm * 2.0) {storage})"
        )
        connection.execute("INSERT INTO scientific_records (id, raw_length_mm) VALUES (1, 3.5)")
    original, upgraded = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["protected_tables_examined"] == 1
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert before.read_bytes() == original
    assert after.read_bytes() == upgraded


def test_no_pk_uses_canonical_column_order_for_record_preservation(tmp_path: Path) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    with sqlite3.connect(before) as connection:
        connection.execute("CREATE TABLE annotations (note TEXT, measurement REAL, blob BLOB)")
        connection.executemany(
            "INSERT INTO annotations VALUES (?, ?, ?)",
            [("b", -0.0, b"\x01"), ("a", 2.5, b"\x02")],
        )
    with sqlite3.connect(after) as connection:
        connection.execute("CREATE TABLE annotations (note TEXT, measurement REAL, blob BLOB)")
        connection.executemany(
            "INSERT INTO annotations VALUES (?, ?, ?)",
            [("a", 2.5, b"\x02"), ("b", -0.0, b"\x01")],
        )
    code, report = _run(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"


@pytest.mark.parametrize("mode", ["same_path", "missing", "corrupt", "no_covered_table"])
def test_fails_closed_on_unsafe_inputs(tmp_path: Path, mode: str) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    if mode == "same_path":
        after = before
    elif mode == "missing":
        after.unlink()
    elif mode == "corrupt":
        after.write_bytes(b"not-a-database")
    elif mode == "no_covered_table":
        with sqlite3.connect(before) as connection:
            for name in (
                "scientific_records",
                "review_queue_item_events",
                "class_visibility_preferences",
                "workflow_graph_records",
                "annotations",
            ):
                connection.execute(f'DROP TABLE "{name}"')
    baseline_bytes = before.read_bytes()
    if after.is_file():
        candidate_bytes = after.read_bytes()
    code, report = _run(before, after)
    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert before.read_bytes() == baseline_bytes
    if after.is_file():
        assert after.read_bytes() == candidate_bytes


def test_wal_sidecar_blocks_preservation_claim(tmp_path: Path) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    writer = sqlite3.connect(after)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("UPDATE scientific_records SET note = note WHERE id = 'z'")
        writer.commit()
        assert Path(str(after) + "-wal").exists()
        code, report = _run(before, after)
        assert code == 2
        assert report["status"] == "HOLD"
        assert "mutable_sqlite_sidecar_detected" in report["problems"]
    finally:
        writer.close()
