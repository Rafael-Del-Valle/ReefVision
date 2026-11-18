"""Non-destructive 1.6 regression for scientific FK timing across offline upgrades."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify-research-row-preservation-16.py"
PRIVATE_COLUMN = "private_site_7781"


def _seed(
    path: Path,
    *,
    style: str,
    first_timing: str,
    second_timing: str | None = None,
    extra_reference: bool = False,
) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO projects VALUES ('site-1')")
        if style == "inline":
            columns = (
                f"id TEXT PRIMARY KEY, {PRIVATE_COLUMN} TEXT REFERENCES projects(id) {first_timing}"
            )
            if second_timing is not None:
                columns += f", secondary_site TEXT REFERENCES projects(id) {second_timing}"
            if extra_reference:
                columns += ", new_reference TEXT REFERENCES projects(id)"
        else:
            columns = f"id TEXT PRIMARY KEY, {PRIVATE_COLUMN} TEXT"
            if second_timing is not None:
                columns += ", secondary_site TEXT"
            if extra_reference:
                columns += ", new_reference TEXT"
            columns += f", FOREIGN KEY ({PRIVATE_COLUMN}) REFERENCES projects(id) {first_timing}"
            if second_timing is not None:
                columns += f", FOREIGN KEY (secondary_site) REFERENCES projects(id) {second_timing}"
            if extra_reference:
                columns += ", FOREIGN KEY (new_reference) REFERENCES projects(id)"
        db.execute(f"CREATE TABLE scientific_records ({columns})")
        if second_timing is not None:
            db.execute(
                f"INSERT INTO scientific_records (id, {PRIVATE_COLUMN}, secondary_site) "
                "VALUES ('observation-1', 'site-1', 'site-1')"
            )
        else:
            db.execute(
                f"INSERT INTO scientific_records (id, {PRIVATE_COLUMN}) "
                "VALUES ('observation-1', 'site-1')"
            )


def _verify(before: Path, after: Path) -> tuple[int, dict]:
    finished = subprocess.run(
        [sys.executable, str(SCRIPT), "--before", str(before), "--after", str(after)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert finished.stdout, finished.stderr
    return finished.returncode, json.loads(finished.stdout)


@pytest.mark.parametrize("style", ["inline", "table"])
@pytest.mark.parametrize(
    ("before_timing", "after_timing", "expected_status"),
    [
        (
            "DEFERRABLE INITIALLY DEFERRED",
            "DEFERRABLE INITIALLY IMMEDIATE",
            "changed_foreign_key_timing_contract",
        ),
        (
            "DEFERRABLE INITIALLY DEFERRED",
            "NOT DEFERRABLE",
            "changed_foreign_key_timing_contract",
        ),
        (
            "DEFERRABLE INITIALLY DEFERRED",
            "",
            "changed_foreign_key_timing_contract",
        ),
        ("", "DEFERRABLE INITIALLY DEFERRED", "changed_foreign_key_timing_contract"),
        ("DEFERRABLE", "DEFERRABLE INITIALLY DEFERRED", "changed_foreign_key_timing_contract"),
        ("DEFERRABLE", "DEFERRABLE INITIALLY IMMEDIATE", "preserved"),
        ("NOT DEFERRABLE", "", "preserved"),
        ("", "NOT DEFERRABLE", "preserved"),
        ("DEFERRABLE INITIALLY DEFERRED", "DEFERRABLE INITIALLY DEFERRED", "preserved"),
    ],
)
def test_scientific_fk_timing_is_preserved(
    tmp_path: Path, style: str, before_timing: str, after_timing: str, expected_status: str
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before, style=style, first_timing=before_timing)
    _seed(after, style=style, first_timing=after_timing)

    with sqlite3.connect(before) as baseline, sqlite3.connect(after) as candidate:
        # SQLite omits DEFERRABLE / INITIALLY from this public metadata.
        assert baseline.execute("PRAGMA foreign_key_list(scientific_records)").fetchall() == (
            candidate.execute("PRAGMA foreign_key_list(scientific_records)").fetchall()
        )
        assert baseline.execute("SELECT * FROM scientific_records").fetchall() == (
            candidate.execute("SELECT * FROM scientific_records").fetchall()
        )
    baseline_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()

    code, report = _verify(before, after)
    scientific = next(row for row in report["tables"] if row["table"] == "scientific_records")
    assert scientific["status"] == expected_status
    assert report["status"] == (
        "PASS_PRESERVATION_ONLY" if expected_status == "preserved" else "HOLD"
    )
    assert code == (0 if expected_status == "preserved" else 2)
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert PRIVATE_COLUMN not in json.dumps(report)
    assert "site-1" not in json.dumps(report)
    assert before.read_bytes() == baseline_bytes
    assert after.read_bytes() == candidate_bytes


@pytest.mark.parametrize("style", ["inline", "table"])
def test_swapping_two_fk_timing_contracts_is_not_hidden_by_an_equal_policy_set(
    tmp_path: Path, style: str
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(
        before,
        style=style,
        first_timing="DEFERRABLE INITIALLY DEFERRED",
        second_timing="NOT DEFERRABLE",
    )
    _seed(
        after,
        style=style,
        first_timing="NOT DEFERRABLE",
        second_timing="DEFERRABLE INITIALLY DEFERRED",
    )
    baseline_bytes, candidate_bytes = before.read_bytes(), after.read_bytes()
    code, report = _verify(before, after)
    scientific = next(row for row in report["tables"] if row["table"] == "scientific_records")
    assert code == 2
    assert report["status"] == "HOLD"
    assert scientific["status"] == "changed_foreign_key_timing_contract"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert PRIVATE_COLUMN not in json.dumps(report)
    assert before.read_bytes() == baseline_bytes
    assert after.read_bytes() == candidate_bytes


@pytest.mark.parametrize("style", ["inline", "table"])
def test_additive_foreign_key_does_not_rewrite_original_fk_timing(
    tmp_path: Path, style: str
) -> None:
    before = tmp_path / "before.sqlite"
    after = tmp_path / "after.sqlite"
    _seed(before, style=style, first_timing="DEFERRABLE INITIALLY DEFERRED")
    _seed(
        after,
        style=style,
        first_timing="DEFERRABLE INITIALLY DEFERRED",
        extra_reference=True,
    )
    original, candidate = before.read_bytes(), after.read_bytes()
    code, report = _verify(before, after)
    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert before.read_bytes() == original
    assert after.read_bytes() == candidate
