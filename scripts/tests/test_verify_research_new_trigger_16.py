"""1.6 preservation-only preflight must not overlook newly injected SQLite triggers."""

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify-research-row-preservation-16.py"
PRIVATE_ID = "private_coral_parent_204"


def _seed(path: Path, table: str, *, mutating_trigger: bool) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"CREATE TABLE {table} (id TEXT PRIMARY KEY, measured_mm REAL NOT NULL)"
        )
        connection.execute(f"INSERT INTO {table} VALUES (?, ?)", (PRIVATE_ID, 3.5))
        if mutating_trigger:
            connection.execute(
                f"CREATE TRIGGER added_future_bias AFTER INSERT ON {table} "
                f"BEGIN UPDATE {table} SET measured_mm = NEW.measured_mm * 2 "
                "WHERE id = NEW.id; END"
            )


def _verify(before: Path, after: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--before", str(before), "--after", str(after)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.stdout, completed.stderr
    return completed.returncode, json.loads(completed.stdout)


@pytest.mark.parametrize("table", ["scientific_records", "review_queue_item_events"])
def test_added_trigger_must_hold_even_with_identical_existing_observations(
    tmp_path: Path, table: str
) -> None:
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    _seed(before, table, mutating_trigger=False)
    _seed(after, table, mutating_trigger=True)
    with sqlite3.connect(before) as baseline, sqlite3.connect(after) as candidate:
        assert baseline.execute(f"SELECT * FROM {table}").fetchall() == candidate.execute(
            f"SELECT * FROM {table}"
        ).fetchall()

    # A disposable future-write oracle demonstrates actual scientific/QC drift
    # without touching either input used by the read-only preservation gate.
    proof_before, proof_after = tmp_path / "proof_before.sqlite", tmp_path / "proof_after.sqlite"
    shutil.copyfile(before, proof_before)
    shutil.copyfile(after, proof_after)
    with sqlite3.connect(proof_before) as baseline, sqlite3.connect(proof_after) as candidate:
        for connection in (baseline, candidate):
            connection.execute(f"INSERT INTO {table} VALUES (?, ?)", ("future", 4.0))
        assert baseline.execute(
            f"SELECT measured_mm FROM {table} WHERE id = 'future'"
        ).fetchone() == (4.0,)
        assert candidate.execute(
            f"SELECT measured_mm FROM {table} WHERE id = 'future'"
        ).fetchone() == (8.0,)

    old_bytes, new_bytes = before.read_bytes(), after.read_bytes()
    code, report = _verify(before, after)
    row = next(entry for entry in report["tables"] if entry["table"] == table)
    assert code == 2
    assert report["status"] == "HOLD"
    assert row["status"] == "changed_trigger_contract"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert PRIVATE_ID not in json.dumps(report)
    assert "added_future_bias" not in json.dumps(report)
    assert before.read_bytes() == old_bytes
    assert after.read_bytes() == new_bytes


def test_trigger_on_entirely_new_table_does_not_rewrite_original_science(
    tmp_path: Path,
) -> None:
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    _seed(before, "scientific_records", mutating_trigger=False)
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        connection.execute("CREATE TABLE added_survey (id TEXT PRIMARY KEY, count INTEGER)")
        connection.execute(
            "CREATE TRIGGER added_survey_audit AFTER INSERT ON added_survey "
            "BEGIN SELECT 1; END"
        )
    old_bytes, new_bytes = before.read_bytes(), after.read_bytes()
    code, report = _verify(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert before.read_bytes() == old_bytes
    assert after.read_bytes() == new_bytes
