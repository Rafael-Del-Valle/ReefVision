"""Strict 1.6 migration review cannot accept a mutable SQLite sidecar snapshot."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect_sqlite_lineage_16.py"


def _create_database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        db.execute("INSERT INTO alembic_version VALUES ('0038')")
        db.execute("CREATE TABLE biological_sentinel (note TEXT)")
        db.execute("INSERT INTO biological_sentinel VALUES ('private coral datum')")


def _run(primary: Path, *options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(primary), *options],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("live_side", ["primary", "reference"])
def test_live_wal_sidecar_requires_review_on_both_comparison_sides(
    tmp_path: Path, live_side: str
) -> None:
    primary = tmp_path / "primary.sqlite"
    reference = tmp_path / "reference.sqlite"
    for path in (primary, reference):
        _create_database(path)
    active = primary if live_side == "primary" else reference
    writer = sqlite3.connect(active)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        reader = sqlite3.connect(active)
        try:
            # Pin an older reader snapshot to keep the committed WAL alive.
            reader.execute("BEGIN")
            assert reader.execute(
                "SELECT COUNT(*) FROM biological_sentinel"
            ).fetchone() == (1,)
            writer.execute(
                "INSERT INTO biological_sentinel VALUES ('private new observation')"
            )
            writer.commit()
            wal = Path(f"{active}-wal")
            shm = Path(f"{active}-shm")
            assert wal.exists() and wal.stat().st_size > 0
            assert shm.exists()
            before = (primary.read_bytes(), reference.read_bytes(), wal.read_bytes())

            command = ("--compare-to", str(reference))
            for strict in (
                (),
                ("--fail-on-integrity-error",),
                ("--fail-on-lineage-collision",),
            ):
                result = _run(primary, *command, *strict)
                assert result.returncode == (2 if strict else 0), result.stderr
                report = json.loads(result.stdout)
                assert report["classification"] == "requires_researcher_review"
                assert report["schema_comparison"]["matches"] is True
                assert report["schema_comparison"]["revision_markers_match"] is True
                live_report = (
                    report
                    if live_side == "primary"
                    else report["schema_comparison"]["reference_integrity"]
                )
                assert live_report["sqlite_sidecar_presence"]["-wal"] is True
                assert live_report["sqlite_sidecar_presence"]["-shm"] is True
                assert live_report["sqlite_sidecar_consistent_snapshot_required"] is True
                assert "private coral" not in result.stdout + result.stderr
                assert "private new observation" not in result.stdout + result.stderr

            assert (
                primary.read_bytes(), reference.read_bytes(), wal.read_bytes()
            ) == before
            assert writer.execute(
                "SELECT COUNT(*) FROM biological_sentinel"
            ).fetchone() == (2,)
        finally:
            reader.close()
    finally:
        writer.close()


def test_rollback_journal_sidecar_requires_review_without_db_mutation(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "rollback.sqlite"
    _create_database(primary)
    writer = sqlite3.connect(primary)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "INSERT INTO biological_sentinel VALUES ('uncommitted private datum')"
        )
        journal = Path(f"{primary}-journal")
        assert journal.exists() and journal.stat().st_size > 0
        before = (primary.read_bytes(), journal.read_bytes())
        diagnostic = _run(primary)
        strict = _run(primary, "--fail-on-integrity-error")
        assert diagnostic.returncode == 0, diagnostic.stderr
        assert strict.returncode == 2, strict.stderr
        for result in (diagnostic, strict):
            report = json.loads(result.stdout)
            assert report["sqlite_sidecar_presence"]["-journal"] is True
            assert report["sqlite_sidecar_consistent_snapshot_required"] is True
            assert report["classification"] == "requires_researcher_review"
            assert "private datum" not in result.stdout + result.stderr
        assert (primary.read_bytes(), journal.read_bytes()) == before
    finally:
        writer.rollback()
        writer.close()


def test_sidecar_free_canonical_stamp_preserves_strict_legacy_success(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "frozen-copy.sqlite"
    _create_database(primary)
    before = primary.read_bytes()
    result = _run(primary, "--fail-on-integrity-error")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["sqlite_sidecar_consistent_snapshot_required"] is False
    assert not any(report["sqlite_sidecar_presence"].values())
    assert report["classification"] == "requires_researcher_review"
    assert "private coral datum" not in result.stdout
    assert primary.read_bytes() == before
