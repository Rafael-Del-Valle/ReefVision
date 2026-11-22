"""Read-only inspection of actual SQLite 0038/0039 schema signatures.

Uses a real SQLite file and the exact distinguishing table and CHECK names
from the two conflicting migrations, not a simulated Alembic revision graph.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def _inspect(tmp_path: Path, ddl: str, revision: str) -> tuple[int, dict[str, object]]:
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        connection.executescript(ddl)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    script = Path(__file__).resolve().parents[4] / "scripts" / "inspect-alembic-0038-sqlite.py"
    result = subprocess.run(
        [sys.executable, str(script), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not path.with_name(path.name + "-journal").exists()
    assert not path.with_name(path.name + "-wal").exists()
    return result.returncode, json.loads(result.stdout)


@pytest.mark.parametrize(
    ("ddl", "revision", "expected"),
    [
        (
            """
            CREATE TABLE scientific_records (
              id TEXT, project_id TEXT, variable TEXT, content_sha256 TEXT
            );
            CREATE TABLE environmental_cache_entries (
              id TEXT, project_id TEXT, cache_key TEXT, source_url TEXT
            );
            """,
            "0038",
            "1.1-scientific-0038",
        ),
        (
            """
            CREATE TABLE review_queue_item_events (
              id TEXT, project_id TEXT, review_queue_id TEXT, review_queue_item_id TEXT,
              client_request_id TEXT, event_type TEXT, actor TEXT,
              CONSTRAINT ck_review_queue_item_event_type CHECK (
                event_type IN ('comment', 'assign', 'unassign',
                               'triage_start', 'triage_skip', 'triage_return')
              )
            );
            """,
            "0039",
            "1.6-qc-0039",
        ),
    ],
)
def test_classifies_conflicting_real_sqlite_schema_without_writing(
    tmp_path: Path,
    ddl: str,
    revision: str,
    expected: str,
) -> None:
    status, report = _inspect(tmp_path, ddl, revision)
    assert status == 0
    assert report["classification"] == expected
    assert report["automatic_migration_authorized"] is False
    assert report["manual_migration_reconciliation_required"] is True


def test_refuses_colliding_version_with_hybrid_tables(tmp_path: Path) -> None:
    ddl = """
        CREATE TABLE scientific_records (
          id TEXT, project_id TEXT, variable TEXT, content_sha256 TEXT
        );
        CREATE TABLE environmental_cache_entries (
          id TEXT, project_id TEXT, cache_key TEXT, source_url TEXT
        );
        CREATE TABLE review_queue_item_events (
          id TEXT, project_id TEXT, review_queue_id TEXT, review_queue_item_id TEXT,
          client_request_id TEXT, event_type TEXT, actor TEXT,
          CHECK(event_type IN ('comment', 'assign', 'unassign'))
        );
    """
    status, report = _inspect(tmp_path, ddl, "0038")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["automatic_migration_authorized"] is False
    assert report["issues"]


def test_qc_lineage_requires_event_check_not_incidental_sql_text(tmp_path: Path) -> None:
    # A comment containing a complete, but non-executed triage CHECK must
    # never override the actual coordination-only CHECK in sqlite_master.
    ddl = """
        CREATE TABLE review_queue_item_events (
          id TEXT, project_id TEXT, review_queue_id TEXT, review_queue_item_id TEXT,
          client_request_id TEXT, event_type TEXT, actor TEXT,
          note TEXT, /*
            CHECK(event_type IN ('comment', 'assign', 'unassign',
                                 'triage_start', 'triage_skip', 'triage_return'))
          */
          CHECK(event_type IN ('comment', 'assign', 'unassign'))
        );
    """
    status, report = _inspect(tmp_path, ddl, "0039")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["review_event_check"] == "coordination"


def test_rejects_qc_event_table_missing_required_review_queue_reference(
    tmp_path: Path,
) -> None:
    # 1.6 migration 0038 requires review_queue_id to link events to review queues.
    # A lookalike table missing that column must not certify installed lineage.
    ddl = """
        CREATE TABLE review_queue_item_events (
          id TEXT, project_id TEXT, review_queue_item_id TEXT,
          client_request_id TEXT, event_type TEXT, actor TEXT,
          CHECK(event_type IN ('comment', 'assign', 'unassign'))
        );
    """
    status, report = _inspect(tmp_path, ddl, "0038")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["table_signatures"]["review_queue_item_events"] is False
    expected_issue = "Incomplete expected table signatures: review_queue_item_events"
    assert expected_issue in report["issues"]
    assert report["automatic_migration_authorized"] is False
