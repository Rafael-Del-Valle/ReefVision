"""Reject unreviewed Alembic-stamp triggers without changing research data."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "inspect-alembic-lineage.py"
SPEC = importlib.util.spec_from_file_location("inspect_alembic_lineage", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize("event", ["INSERT", "UPDATE", "DELETE"])
def test_desktop_blocks_revision_triggers_before_any_migration_write(
    tmp_path: Path, event: str
) -> None:
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version VALUES ('0037')")
        db.execute("CREATE TABLE coral_sentinel (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
        db.execute("INSERT INTO coral_sentinel VALUES (1, 'unpublished coral observation')")
        # This would erase an observation if Alembic performed the corresponding
        # stamp operation. The preflight must never fire, remove or repair it.
        db.execute(
            f"CREATE TRIGGER private_coral_study AFTER {event} ON alembic_version "
            "BEGIN DELETE FROM coral_sentinel; END"
        )
        db.commit()

    original = path.read_bytes()
    report = module.inspect(path)
    assert report["alembic_version_trigger_count"] == 1
    assert "alembic_version_triggers_require_review" in report["warnings"]
    assert report["upgrade_authorized"] is False
    assert "private_coral_study" not in json.dumps(report)
    assert "unpublished coral observation" not in json.dumps(report)

    engine = create_engine(f"sqlite+pysqlite:///{path.as_posix()}")
    with engine.connect() as connection:
        with pytest.raises(RuntimeError, match="version-table trigger"):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0037"
        assert connection.scalar(text("SELECT note FROM coral_sentinel")) == (
            "unpublished coral observation"
        )
    engine.dispose()
    assert path.read_bytes() == original


@pytest.mark.parametrize("with_trigger", [False, True])
def test_read_only_cli_reports_stamp_trigger_and_strictly_rejects_it(
    tmp_path: Path, with_trigger: bool
) -> None:
    # Revision 0039 is a valid independent QC stage for the standalone
    # inspector; the desktop guard deliberately requires richer QC topology.
    path = tmp_path / "qc-review.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version VALUES ('0039')")
        db.execute("CREATE TABLE review_queue_item_events (id TEXT PRIMARY KEY, note TEXT)")
        db.execute(
            "INSERT INTO review_queue_item_events VALUES ('item-1', 'private reviewer decision')"
        )
        if with_trigger:
            db.execute(
                "CREATE TRIGGER private_decision AFTER UPDATE ON alembic_version "
                "BEGIN DELETE FROM review_queue_item_events; END"
            )
        db.commit()

    original = path.read_bytes()
    report = module.inspect(path)
    assert report["lineage_hint"] == "qc"
    assert report["canonical_alembic_stamp_constraints"] is True
    assert report["alembic_version_trigger_count"] == int(with_trigger)
    assert report["warnings"] == (
        ["alembic_version_triggers_require_review"] if with_trigger else []
    )
    assert report["inventory"]["review_queue_item_events"]["rows"] == 1
    assert report["upgrade_authorized"] is False
    assert "private_decision" not in json.dumps(report)
    assert "private reviewer decision" not in json.dumps(report)

    strict = subprocess.run(
        [sys.executable, str(SCRIPT), str(path), "--fail-on-warning"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict.returncode == (2 if with_trigger else 0)
    assert json.loads(strict.stdout)["warnings"] == report["warnings"]
    assert path.read_bytes() == original


def test_unrelated_research_trigger_is_not_falsely_classified_as_stamp_trigger(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version VALUES ('0037')")
        db.execute("CREATE TABLE coral_sentinel (id INTEGER PRIMARY KEY, note TEXT)")
        db.execute("INSERT INTO coral_sentinel VALUES (1, 'preserved')")
        db.execute(
            "CREATE TRIGGER unrelated_coral_audit AFTER UPDATE ON coral_sentinel "
            "BEGIN SELECT 1; END"
        )
        db.commit()

    original = path.read_bytes()
    report = module.inspect(path)
    assert report["alembic_version_trigger_count"] == 0
    assert "alembic_version_triggers_require_review" not in report["warnings"]
    engine = create_engine(f"sqlite+pysqlite:///{path.as_posix()}")
    with engine.connect() as connection:
        assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT note FROM coral_sentinel")) == "preserved"
    engine.dispose()
    assert path.read_bytes() == original
