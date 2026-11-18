"""Read-only scientific SQL view preservation across 1.1/1.6 offline upgrades."""

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify-research-row-preservation-16.py"
PRIVATE_VIEW = "private_field_site_reef_survey"


def _seed(path: Path, *, select_star: bool = False) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE scientific_records (id TEXT PRIMARY KEY, length_mm REAL NOT NULL, "
            "private_note TEXT)"
        )
        connection.execute(
            "INSERT INTO scientific_records VALUES (?, ?, ?)",
            ("coral-001", 0.0, "private-benthic-survey-notes"),
        )
        expression = (
            "SELECT * FROM scientific_records"
            if select_star
            else "SELECT id, length_mm * 1.0 AS adjusted_mm FROM scientific_records"
        )
        connection.execute(f'CREATE VIEW "{PRIVATE_VIEW}" AS {expression}')


def _run(before: Path, after: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--before", str(before), "--after", str(after)],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


@pytest.mark.parametrize(
    ("mutation", "expected_problem"),
    [
        ("drop", "research_views_missing"),
        ("replace_formula", "research_view_contract_changed"),
        ("rename", "research_views_missing"),
        ("additive_column_changes_star_shape", "research_view_contract_changed"),
    ],
)
def test_preexisting_scientific_view_contract_must_survive(
    tmp_path: Path, mutation: str, expected_problem: str
) -> None:
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    _seed(before, select_star=mutation == "additive_column_changes_star_shape")
    shutil.copyfile(before, after)

    with sqlite3.connect(after) as connection:
        if mutation == "additive_column_changes_star_shape":
            # Adding a table column is otherwise permitted, but SELECT * views
            # silently change their exported scientific result schema.
            connection.execute(
                "ALTER TABLE scientific_records ADD COLUMN extra_measurement_mm REAL"
            )
        else:
            connection.execute(f'DROP VIEW "{PRIVATE_VIEW}"')
            if mutation == "replace_formula":
                # All current measurements are zero: old and new view rows agree,
                # but future biological measurements would be doubled.
                connection.execute(
                    f'CREATE VIEW "{PRIVATE_VIEW}" AS '
                    "SELECT id, length_mm * 2.0 AS adjusted_mm FROM scientific_records"
                )
            elif mutation == "rename":
                connection.execute(
                    "CREATE VIEW a_different_view AS SELECT id, length_mm FROM scientific_records"
                )

    if mutation == "replace_formula":
        with sqlite3.connect(before) as old, sqlite3.connect(after) as new:
            sql = f'SELECT * FROM "{PRIVATE_VIEW}"'
            assert old.execute(sql).fetchall() == new.execute(sql).fetchall()

    old_bytes, new_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)

    assert code == 2
    assert report["status"] == "HOLD"
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert expected_problem in report["problems"]
    views = report["research_views"]
    assert views["checked"] is True
    assert views["baseline_views"] == 1
    assert views["missing_views"] == (1 if expected_problem == "research_views_missing" else 0)
    assert views["changed_views"] == (
        1 if expected_problem == "research_view_contract_changed" else 0
    )
    # Diagnostic counts are public; researcher-defined view SQL, identifiers,
    # biological records and private notes are not.
    public = json.dumps(report, ensure_ascii=False)
    for secret in (PRIVATE_VIEW, "coral-001", "private-benthic-survey-notes", "adjusted_mm"):
        assert secret not in public
    assert before.read_bytes() == old_bytes
    assert after.read_bytes() == new_bytes


@pytest.mark.parametrize("mutation", ["unchanged", "additional_view", "spacing_only"])
def test_preserved_or_additive_views_are_compatible(tmp_path: Path, mutation: str) -> None:
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    _seed(before)
    shutil.copyfile(before, after)
    with sqlite3.connect(after) as connection:
        if mutation == "additional_view":
            connection.execute(
                "CREATE VIEW new_analysis AS SELECT length_mm FROM scientific_records"
            )
        elif mutation == "spacing_only":
            connection.execute(f'DROP VIEW "{PRIVATE_VIEW}"')
            connection.execute(
                f'create   view "{PRIVATE_VIEW}" as   select id, '
                "length_mm * 1.0 as adjusted_mm from scientific_records"
            )
    old_bytes, new_bytes = before.read_bytes(), after.read_bytes()
    code, report = _run(before, after)

    assert code == 0
    assert report["status"] == "PASS_PRESERVATION_ONLY"
    assert not report["problems"]
    assert report["research_views"]["baseline_views"] == 1
    assert report["research_views"]["candidate_views"] == (
        2 if mutation == "additional_view" else 1
    )
    assert report["research_views"]["missing_views"] == 0
    assert report["research_views"]["changed_views"] == 0
    assert report["upgrade_authorized"] is False
    assert report["requires_researcher_approval"] is True
    assert before.read_bytes() == old_bytes
    assert after.read_bytes() == new_bytes
