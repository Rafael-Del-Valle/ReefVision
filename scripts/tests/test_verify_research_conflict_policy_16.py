"""Preserve future biological-write conflict behavior in offline 1.6 upgrades."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify-research-row-preservation-16.py"
PRIVATE_SITE = "private_study_label_105"


def _seed(
    path: Path,
    *,
    style: str,
    policy: str = "",
    extra_column: bool = False,
    extra_unique: bool = False,
) -> None:
    clause = f" ON CONFLICT {policy}" if policy else ""
    columns = {
        "inline_unique": f"id TEXT PRIMARY KEY, sample TEXT UNIQUE{clause}",
        "table_unique": f"id TEXT PRIMARY KEY, sample TEXT, UNIQUE(sample){clause}",
        "inline_primary": f"id TEXT PRIMARY KEY{clause}, sample TEXT",
        "table_primary": f"id TEXT, sample TEXT, PRIMARY KEY(id){clause}",
        "not_null": f"id TEXT PRIMARY KEY, sample TEXT NOT NULL{clause}",
    }[style]
    if extra_column:
        # SQLite requires all column declarations before table-level
        # constraints; insert the additive field ahead of those constraints.
        if style == "table_unique":
            columns = columns.replace(
                ", UNIQUE(sample)", ", additional_measurement_mm REAL, UNIQUE(sample)", 1
            )
        elif style == "table_primary":
            columns = columns.replace(
                ", PRIMARY KEY(id)", ", additional_measurement_mm REAL, PRIMARY KEY(id)", 1
            )
        else:
            columns += ", additional_measurement_mm REAL"
    if extra_unique:
        columns += ", UNIQUE(id, sample)"
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE scientific_records ({columns})")
        db.execute(
            "INSERT INTO scientific_records (id, sample) VALUES (?, ?)",
            ("reef-1", PRIVATE_SITE),
        )


def _run(before: Path, after: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--before", str(before), "--after", str(after)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.stdout, completed.stderr
    return completed.returncode, json.loads(completed.stdout)


def _semantic_index_contracts(connection: sqlite3.Connection) -> list[tuple]:
    """Compare effective constraints, not SQLite-generated autoindex names/order.

    SQLite can reorder PRAGMA index_list when ON CONFLICT changes, even when
    unique-key columns, collation and index origins remain unchanged.
    """
    contracts = []
    for _, name, unique, origin, partial in connection.execute(
        "PRAGMA index_list(scientific_records)"
    ):
        escaped = name.replace('"', '""')
        keys = tuple(
            (column[2], column[3], column[4])
            for column in connection.execute(f'PRAGMA index_xinfo("{escaped}")')
            if column[5]
        )
        contracts.append((unique, origin, partial, keys))
    return sorted(contracts)


@pytest.mark.parametrize(
    ("style", "before_policy", "after_policy"),
    [
        ("inline_unique", "", "IGNORE"),
        ("table_unique", "", "REPLACE"),
        ("inline_primary", "REPLACE", "IGNORE"),
        ("table_primary", "FAIL", "ROLLBACK"),
        ("not_null", "", "IGNORE"),
        ("inline_unique", "IGNORE", ""),
        ("table_unique", "REPLACE", "ABORT"),
    ],
)
def test_changed_sqlite_conflict_policy_holds_without_writing_data(
    tmp_path: Path, style: str, before_policy: str, after_policy: str
) -> None:
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    _seed(before, style=style, policy=before_policy)
    _seed(after, style=style, policy=after_policy)
    with sqlite3.connect(before) as old, sqlite3.connect(after) as new:
        assert (
            old.execute("SELECT * FROM scientific_records").fetchall()
            == new.execute("SELECT * FROM scientific_records").fetchall()
        )
        assert (
            old.execute("PRAGMA table_xinfo(scientific_records)").fetchall()
            == new.execute("PRAGMA table_xinfo(scientific_records)").fetchall()
        )
        assert _semantic_index_contracts(old) == _semantic_index_contracts(new)
    original_before, original_after = before.read_bytes(), after.read_bytes()

    status, report = _run(before, after)
    scientific = next(item for item in report["tables"] if item["table"] == "scientific_records")
    assert status == 2
    assert report["status"] == "HOLD"
    assert scientific["status"] == "changed_constraint_conflict_policy"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert PRIVATE_SITE not in json.dumps(report)
    assert before.read_bytes() == original_before
    assert after.read_bytes() == original_after


@pytest.mark.parametrize("style", ["inline_unique", "table_unique", "not_null"])
def test_preserved_conflict_policy_and_additive_columns_pass_preservation_only(
    tmp_path: Path, style: str
) -> None:
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    _seed(before, style=style, policy="IGNORE")
    _seed(after, style=style, policy="IGNORE", extra_column=True, extra_unique=True)
    original_before, original_after = before.read_bytes(), after.read_bytes()

    status, report = _run(before, after)
    assert status == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert not report["problems"]
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert before.read_bytes() == original_before
    assert after.read_bytes() == original_after


def _seed_swapped(path: Path, *, swap_and_reorder: bool) -> None:
    first = "UNIQUE(sample) ON CONFLICT IGNORE"
    second = f"UNIQUE({PRIVATE_SITE}) ON CONFLICT REPLACE"
    if swap_and_reorder:
        # Preserve the global IGNORE, REPLACE sequence while moving the rules
        # to different scientifically meaningful unique fields.
        first = f"UNIQUE({PRIVATE_SITE}) ON CONFLICT IGNORE"
        second = "UNIQUE(sample) ON CONFLICT REPLACE"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE scientific_records "
            f"(id TEXT PRIMARY KEY, sample TEXT, {PRIVATE_SITE} TEXT, {first}, {second})"
        )
        db.execute(
            f"INSERT INTO scientific_records (id, sample, {PRIVATE_SITE}) VALUES (?, ?, ?)",
            ("reef-1", "polyp-count", "sample-A"),
        )


def test_reordered_unique_constraints_cannot_swap_which_observation_is_replaced(
    tmp_path: Path,
) -> None:
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    _seed_swapped(before, swap_and_reorder=False)
    _seed_swapped(after, swap_and_reorder=True)
    original_before, original_after = before.read_bytes(), after.read_bytes()
    status, report = _run(before, after)
    scientific = next(item for item in report["tables"] if item["table"] == "scientific_records")
    assert status == 2
    assert scientific["status"] == "changed_constraint_conflict_policy"
    assert report["upgrade_authorized"] is False
    assert PRIVATE_SITE not in json.dumps(report)
    assert before.read_bytes() == original_before
    assert after.read_bytes() == original_after


def test_conflict_policy_matters_even_when_prior_observations_match() -> None:
    """Demonstrate actual SQLite future-write behavior in disposable memory."""
    outcomes = []
    for policy in ("", "IGNORE", "REPLACE"):
        clause = f" ON CONFLICT {policy}" if policy else ""
        with sqlite3.connect(":memory:") as db:
            db.execute(f"CREATE TABLE survey (id TEXT PRIMARY KEY, site TEXT UNIQUE{clause})")
            db.execute("INSERT INTO survey VALUES ('original', 'same-site')")
            try:
                db.execute("INSERT INTO survey VALUES ('new', 'same-site')")
            except sqlite3.IntegrityError:
                outcomes.append("rejected")
            else:
                outcomes.append(db.execute("SELECT id FROM survey").fetchone()[0])
    assert outcomes == ["rejected", "original", "new"]
