"""Read-only SQLite format-header migration diagnostics for ReefVision 1.6."""

import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_sqlite_lineage_16.py"


def _create_database(
    path: Path, *, application_id: int, user_version: int, bump_schema_cookie: bool
) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version VALUES ('0038')")
        db.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, note TEXT)")
        db.execute("INSERT INTO scientific_records VALUES (1, 'private coral coordinates')")
        if bump_schema_cookie:
            db.execute("CREATE TABLE transitory_probe (id INTEGER)")
            db.execute("DROP TABLE transitory_probe")
        db.execute(f"PRAGMA application_id = {application_id}")
        db.execute(f"PRAGMA user_version = {user_version}")
        db.commit()


@pytest.mark.parametrize(
    (
        "source_application",
        "reference_application",
        "source_user",
        "reference_user",
        "expected_fields",
    ),
    [
        (10, 10, 2, 2, []),
        (10, 11, 2, 2, ["application_id"]),
        (10, 10, 2, 3, ["user_version"]),
        (10, 11, 2, 3, ["application_id", "user_version"]),
    ],
)
def test_format_header_gate_is_read_only_and_independent_of_ddl(
    tmp_path: Path,
    source_application: int,
    reference_application: int,
    source_user: int,
    reference_user: int,
    expected_fields: list[str],
) -> None:
    source = tmp_path / "source.sqlite"
    reference = tmp_path / "reference.sqlite"
    _create_database(
        source,
        application_id=source_application,
        user_version=source_user,
        bump_schema_cookie=False,
    )
    _create_database(
        reference,
        application_id=reference_application,
        user_version=reference_user,
        bump_schema_cookie=True,
    )
    original = (source.read_bytes(), reference.read_bytes())
    command = [
        sys.executable,
        str(SCRIPT),
        str(source),
        "--compare-to",
        str(reference),
    ]
    diagnostic = subprocess.run(command, capture_output=True, text=True, check=False)
    strict = subprocess.run(
        [*command, "--fail-on-format-header-drift"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert diagnostic.returncode == 0, diagnostic.stderr
    assert strict.returncode == (2 if expected_fields else 0), strict.stderr
    assert not strict.stderr
    report = json.loads(strict.stdout)
    assert report == json.loads(diagnostic.stdout)
    comparison = report["schema_comparison"]
    assert comparison["matches"] is True
    assert comparison["revision_markers_match"] is True
    assert comparison["only_in_database"] == []
    assert comparison["only_in_reference"] == []
    assert comparison["changed_definitions"] == []
    assert comparison["requires_researcher_review"] is True
    assert report["classification"] == "requires_researcher_review"
    assert (
        report["sqlite_header"]["schema_version"]
        != comparison["reference_sqlite_header"]["schema_version"]
    )
    assert [entry["field"] for entry in comparison["format_header_differences"]] == (
        expected_fields
    )
    for entry in comparison["format_header_differences"]:
        assert entry["database_value"] == report["sqlite_header"][entry["field"]]
        assert entry["reference_value"] == comparison["reference_sqlite_header"][entry["field"]]
    assert "private coral coordinates" not in strict.stdout
    assert "private coral coordinates" not in strict.stderr
    assert (source.read_bytes(), reference.read_bytes()) == original
    with closing(sqlite3.connect(source)) as db:
        assert db.execute("SELECT note FROM scientific_records").fetchone() == (
            "private coral coordinates",
        )


def test_format_header_gate_requires_independent_database(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _create_database(source, application_id=10, user_version=2, bump_schema_cookie=False)
    before = source.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--fail-on-format-header-drift"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "requires --compare-to" in result.stderr
    assert source.read_bytes() == before
