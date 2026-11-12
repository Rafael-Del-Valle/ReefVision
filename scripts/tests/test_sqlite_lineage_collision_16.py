"""A matching Alembic stamp is not proof of matching SQLite schema lineage."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect_sqlite_lineage_16.py"


def _database(path: Path, *, revision: str, divergent: bool) -> bytes:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        connection.execute("CREATE TABLE observations (private_note TEXT)")
        if divergent:
            connection.execute("CREATE TABLE new_review_evidence (item_id TEXT)")
        connection.execute("INSERT INTO observations VALUES ('confidential coral')")
    return path.read_bytes()


@pytest.mark.parametrize(
    ("reference_revision", "divergent", "expected_exit"),
    [
        ("0038", True, 2),
        ("0038", False, 0),
        ("0039", True, 2),
        ("0039", False, 2),
    ],
)
def test_collision_gate_preserves_data_and_requires_review(
    tmp_path: Path, reference_revision: str, divergent: bool, expected_exit: int
) -> None:
    primary = tmp_path / "primary.sqlite"
    reference = tmp_path / "reference.sqlite"
    primary_bytes = _database(primary, revision="0038", divergent=False)
    reference_bytes = _database(
        reference, revision=reference_revision, divergent=divergent
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(primary),
            "--compare-to",
            str(reference),
            "--fail-on-lineage-collision",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_exit, result.stderr
    report = json.loads(result.stdout)
    assert report["classification"] == "requires_researcher_review"
    assert report["schema_comparison"]["requires_researcher_review"] is True
    assert report["schema_comparison"]["revision_markers_match"] == (
        reference_revision == "0038"
    )
    assert report["schema_comparison"]["matches"] is (not divergent)
    # Collision mode is fail-closed for uncertain or different revision lineage.
    assert (result.returncode == 0) is (
        reference_revision == "0038" and not divergent
    )
    assert "confidential coral" not in result.stdout + result.stderr
    assert primary.read_bytes() == primary_bytes
    assert reference.read_bytes() == reference_bytes


def test_collision_gate_requires_reference(tmp_path: Path) -> None:
    primary = tmp_path / "primary.sqlite"
    _database(primary, revision="0038", divergent=False)
    before = primary.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(primary), "--fail-on-lineage-collision"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--fail-on-lineage-collision requires --compare-to" in result.stderr
    assert result.stdout == ""
    assert primary.read_bytes() == before


@pytest.mark.parametrize("noncanonical_side", ["primary", "reference"])
def test_collision_gate_rejects_noncanonical_stamp_constraints(
    tmp_path: Path, noncanonical_side: str
) -> None:
    primary = tmp_path / "primary.sqlite"
    reference = tmp_path / "reference.sqlite"
    _database(primary, revision="0038", divergent=False)
    _database(reference, revision="0038", divergent=False)
    target = primary if noncanonical_side == "primary" else reference
    with sqlite3.connect(target) as connection:
        connection.execute("ALTER TABLE alembic_version RENAME TO old_alembic_version")
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute(
            "INSERT INTO alembic_version SELECT version_num FROM old_alembic_version"
        )
        connection.execute("DROP TABLE old_alembic_version")
    before = (primary.read_bytes(), reference.read_bytes())
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), str(primary),
            "--compare-to", str(reference), "--fail-on-lineage-collision",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["classification"] == "requires_researcher_review"
    assert report["schema_comparison"]["requires_researcher_review"] is True
    # A matching text stamp on a noncanonical table is not a validated match.
    assert report["schema_comparison"]["revision_markers_match"] is False
    assert (
        report["alembic_stamp_constraint_error"] is not None
        or report["schema_comparison"]["reference_integrity"][
            "alembic_stamp_constraint_error"
        ] is not None
    )
    assert "confidential coral" not in result.stdout + result.stderr
    assert (primary.read_bytes(), reference.read_bytes()) == before


@pytest.mark.parametrize("invalid_side", ["primary", "reference"])
def test_collision_gate_rejects_matching_schema_with_broken_foreign_keys(
    tmp_path: Path, invalid_side: str
) -> None:
    """Identical revision and DDL cannot hide a broken biological reference."""
    primary = tmp_path / "primary.sqlite"
    reference = tmp_path / "reference.sqlite"
    for path in (primary, reference):
        _database(path, revision="0038", divergent=False)
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE samples (parent_id INTEGER REFERENCES parents(id))"
            )
            connection.execute("INSERT INTO parents VALUES (1)")
            connection.execute("INSERT INTO samples VALUES (1)")
    target = primary if invalid_side == "primary" else reference
    # SQLite permits legacy databases with orphaned FK values when enforcement
    # was disabled; the read-only inspector must still reject this evidence.
    with sqlite3.connect(target) as connection:
        connection.execute("INSERT INTO samples VALUES (999)")
    before = (primary.read_bytes(), reference.read_bytes())
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(primary),
            "--compare-to",
            str(reference),
            "--fail-on-lineage-collision",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_comparison"]["matches"] is True
    assert report["schema_comparison"]["revision_markers_match"] is True
    assert report["classification"] == "requires_researcher_review"
    if invalid_side == "primary":
        assert report["foreign_key_violation_count"] == 1
    else:
        assert (
            report["schema_comparison"]["reference_integrity"][
                "foreign_key_violation_count"
            ]
            == 1
        )
    assert "confidential coral" not in result.stdout + result.stderr
    assert (primary.read_bytes(), reference.read_bytes()) == before


@pytest.mark.parametrize("invalid_side", ["primary", "reference"])
def test_integrity_gate_rejects_noncanonical_alembic_constraints(
    tmp_path: Path, invalid_side: str
) -> None:
    """Integrity acceptance must reject ambiguous stamps on either side."""
    primary = tmp_path / "primary.sqlite"
    reference = tmp_path / "reference.sqlite"
    _database(primary, revision="0038", divergent=False)
    _database(reference, revision="0038", divergent=False)
    target = primary if invalid_side == "primary" else reference
    with sqlite3.connect(target) as connection:
        connection.execute("ALTER TABLE alembic_version RENAME TO old_alembic_version")
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute(
            "INSERT INTO alembic_version SELECT version_num FROM old_alembic_version"
        )
        connection.execute("DROP TABLE old_alembic_version")
    before = (primary.read_bytes(), reference.read_bytes())
    command = [
        sys.executable,
        str(SCRIPT),
        str(primary),
        "--compare-to",
        str(reference),
    ]
    diagnostic = subprocess.run(command, capture_output=True, text=True, check=False)
    assert diagnostic.returncode == 0, diagnostic.stderr
    report = json.loads(diagnostic.stdout)
    assert report["classification"] == "requires_researcher_review"
    assert (
        report["alembic_stamp_constraint_error"] is not None
        or report["schema_comparison"]["reference_integrity"][
            "alembic_stamp_constraint_error"
        ] is not None
    )
    strict = subprocess.run(
        command + ["--fail-on-integrity-error"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict.returncode == 2, strict.stderr
    assert json.loads(strict.stdout)["classification"] == "requires_researcher_review"
    assert "confidential coral" not in diagnostic.stdout + strict.stdout + strict.stderr
    assert (primary.read_bytes(), reference.read_bytes()) == before
