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
            CREATE TABLE projects (id TEXT PRIMARY KEY);
            CREATE TABLE review_queues (
              id TEXT PRIMARY KEY, project_id TEXT NOT NULL
            );
            CREATE TABLE review_queue_items (
              id TEXT PRIMARY KEY, review_queue_id TEXT NOT NULL, project_id TEXT NOT NULL
            );
            CREATE TABLE review_queue_item_events (
              id TEXT PRIMARY KEY NOT NULL, project_id TEXT NOT NULL,
              review_queue_id TEXT NOT NULL, review_queue_item_id TEXT NOT NULL,
              client_request_id TEXT NOT NULL, event_type TEXT NOT NULL,
              actor TEXT NOT NULL, created_at TEXT NOT NULL,
              CONSTRAINT ck_review_queue_item_event_type CHECK (
                event_type IN ('comment', 'assign', 'unassign',
                               'triage_start', 'triage_skip', 'triage_return')
              ),
              UNIQUE(review_queue_item_id, client_request_id),
              FOREIGN KEY (review_queue_id) REFERENCES review_queues(id) ON DELETE CASCADE,
              FOREIGN KEY (review_queue_item_id) REFERENCES review_queue_items(id)
                ON DELETE CASCADE,
              FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
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
    if expected.startswith("1.6-qc"):
        assert report["qc_request_key_unique"] is True
        assert report["qc_required_columns_not_null"] is True
        assert report["qc_event_foreign_keys_valid"] is True
        assert report["qc_event_scope_violations"] == 0
    assert report["automatic_migration_authorized"] is False
    assert report["manual_migration_reconciliation_required"] is True


def test_rejects_qc_lineage_with_wrong_cascade_foreign_key(
    tmp_path: Path,
) -> None:
    # Actual 1.6/0038 migration requires all three ON DELETE CASCADE links.
    # Existing rows and PRAGMA foreign_key_check cannot prove those links exist.
    ddl = """
        CREATE TABLE projects (id TEXT PRIMARY KEY);
        CREATE TABLE review_queues (id TEXT PRIMARY KEY, project_id TEXT NOT NULL);
        CREATE TABLE review_queue_items (
          id TEXT PRIMARY KEY, review_queue_id TEXT NOT NULL, project_id TEXT NOT NULL
        );
        CREATE TABLE review_queue_item_events (
          id TEXT PRIMARY KEY NOT NULL, project_id TEXT NOT NULL,
          review_queue_id TEXT NOT NULL, review_queue_item_id TEXT NOT NULL,
          client_request_id TEXT NOT NULL, event_type TEXT NOT NULL,
          actor TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(review_queue_item_id, client_request_id),
          CHECK(event_type IN ('comment', 'assign', 'unassign')),
          FOREIGN KEY (review_queue_id) REFERENCES review_queues(id) ON DELETE CASCADE,
          FOREIGN KEY (review_queue_item_id) REFERENCES review_queue_items(id)
            ON DELETE CASCADE,
          FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE NO ACTION
        );
    """
    status, report = _inspect(tmp_path, ddl, "0038")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["review_event_check"] == "coordination"
    assert report["qc_event_scope_violations"] == 0
    assert report["foreign_key_violations"] == 0
    assert report["qc_request_key_unique"] is True
    assert report["qc_required_columns_not_null"] is True
    assert report["qc_event_foreign_keys_valid"] is False
    assert any("CASCADE foreign keys" in issue for issue in report["issues"])
    assert report["automatic_migration_authorized"] is False


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


def test_quoted_sql_identifier_cannot_impersonate_qc_triage_check(
    tmp_path: Path,
) -> None:
    # This is executable SQLite DDL, not a mocked sqlite_master entry.
    # A quoted column name advertises a triage CHECK, but the only enforced
    # event_type constraint permits coordination events. At 0039, reject it.
    ddl = """
        CREATE TABLE review_queue_item_events (
          id TEXT, project_id TEXT, review_queue_id TEXT, review_queue_item_id TEXT,
          client_request_id TEXT, event_type TEXT, actor TEXT,
          "CHECK(event_type IN (
            'comment', 'assign', 'unassign',
            'triage_start', 'triage_skip', 'triage_return'
          ))" TEXT,
          CHECK(event_type IN ('comment', 'assign', 'unassign'))
        );
    """
    status, report = _inspect(tmp_path, ddl, "0039")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["review_event_check"] == "coordination"
    assert report["automatic_migration_authorized"] is False
    assert "Cannot safely attribute the colliding revision" in " ".join(report["issues"])


def test_refuses_populated_qc_lineage_with_cross_project_event(
    tmp_path: Path,
) -> None:
    # The actual 1.6/0039 migration refuses this historical data even when
    # every foreign-key parent exists. A version marker and a valid event
    # CHECK cannot certify a database whose append-only audit scope is broken.
    ddl = """
        CREATE TABLE projects (id TEXT PRIMARY KEY);
        CREATE TABLE review_queues (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL
        );
        CREATE TABLE review_queue_items (
          id TEXT PRIMARY KEY, review_queue_id TEXT NOT NULL, project_id TEXT NOT NULL
        );
        CREATE TABLE review_queue_item_events (
          id TEXT, project_id TEXT, review_queue_id TEXT, review_queue_item_id TEXT,
          client_request_id TEXT, event_type TEXT, actor TEXT,
          FOREIGN KEY (review_queue_id) REFERENCES review_queues(id),
          FOREIGN KEY (review_queue_item_id) REFERENCES review_queue_items(id),
          FOREIGN KEY (project_id) REFERENCES projects(id),
          CHECK(event_type IN (
            'comment', 'assign', 'unassign',
            'triage_start', 'triage_skip', 'triage_return'
          ))
        );
        INSERT INTO projects VALUES ('project-a'), ('project-b');
        INSERT INTO review_queues VALUES ('queue-1', 'project-a');
        INSERT INTO review_queue_items VALUES ('item-1', 'queue-1', 'project-b');
        INSERT INTO review_queue_item_events VALUES (
          'event-1', 'project-a', 'queue-1', 'item-1',
          'request-1', 'comment', 'scientist'
        );
    """
    status, report = _inspect(tmp_path, ddl, "0039")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["review_event_check"] == "triage"
    assert report["qc_event_scope_violations"] == 1
    assert report["automatic_migration_authorized"] is False
    assert any("cross-project links" in issue for issue in report["issues"])


def test_rejects_historical_qc_event_types_outside_installed_check(
    tmp_path: Path,
) -> None:
    # Exercise a persisted real SQLite record produced with CHECK enforcement
    # disabled. A valid-looking 1.6/0038 schema is not sufficient evidence if
    # its scientific review history violates the migration's event contract.
    ddl = """
        CREATE TABLE projects (id TEXT PRIMARY KEY);
        CREATE TABLE review_queues (id TEXT PRIMARY KEY, project_id TEXT NOT NULL);
        CREATE TABLE review_queue_items (
          id TEXT PRIMARY KEY, review_queue_id TEXT NOT NULL, project_id TEXT NOT NULL
        );
        CREATE TABLE review_queue_item_events (
          id TEXT, project_id TEXT, review_queue_id TEXT, review_queue_item_id TEXT,
          client_request_id TEXT, event_type TEXT, actor TEXT,
          CHECK(event_type IN ('comment', 'assign', 'unassign'))
        );
        INSERT INTO projects VALUES ('project-1');
        INSERT INTO review_queues VALUES ('queue-1', 'project-1');
        INSERT INTO review_queue_items VALUES ('item-1', 'queue-1', 'project-1');
        PRAGMA ignore_check_constraints=ON;
        INSERT INTO review_queue_item_events VALUES (
          'event-1', 'project-1', 'queue-1', 'item-1',
          'request-1', 'triage_start', 'scientist'
        );
        PRAGMA ignore_check_constraints=OFF;
    """
    status, report = _inspect(tmp_path, ddl, "0038")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["review_event_check"] == "coordination"
    assert report["qc_event_scope_violations"] == 0
    assert report["qc_event_type_violations"] == 1
    assert report["automatic_migration_authorized"] is False
    assert any("disallowed event types" in issue for issue in report["issues"])


def test_rejects_nullable_historical_qc_parent_queue_link(tmp_path: Path) -> None:
    # An imported or legacy parent table can retain nullable references.
    # SQL "!=" ignores NULL and previously certified this corrupt event
    # even though its item no longer belongs to the recorded review queue.
    ddl = """
        CREATE TABLE projects (id TEXT PRIMARY KEY);
        CREATE TABLE review_queues (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL
        );
        CREATE TABLE review_queue_items (
          id TEXT PRIMARY KEY, review_queue_id TEXT, project_id TEXT NOT NULL
        );
        CREATE TABLE review_queue_item_events (
          id TEXT, project_id TEXT, review_queue_id TEXT, review_queue_item_id TEXT,
          client_request_id TEXT, event_type TEXT, actor TEXT,
          CHECK(event_type IN (
            'comment', 'assign', 'unassign',
            'triage_start', 'triage_skip', 'triage_return'
          ))
        );
        INSERT INTO projects VALUES ('project-1');
        INSERT INTO review_queues VALUES ('queue-1', 'project-1');
        INSERT INTO review_queue_items VALUES ('item-1', NULL, 'project-1');
        INSERT INTO review_queue_item_events VALUES (
          'event-1', 'project-1', 'queue-1', 'item-1',
          'request-1', 'comment', 'scientist'
        );
    """
    status, report = _inspect(tmp_path, ddl, "0039")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["review_event_check"] == "triage"
    assert report["qc_event_scope_violations"] == 1
    assert report["automatic_migration_authorized"] is False
    assert any("orphaned or cross-project links" in issue for issue in report["issues"])


def test_rejects_persisted_scientific_lineage_with_orphaned_foreign_key(
    tmp_path: Path,
) -> None:
    # A valid-looking 1.1/0038 table signature cannot certify science with
    # a broken persisted project FK, even if SQLite enforcement was disabled.
    ddl = """
        CREATE TABLE projects (id TEXT PRIMARY KEY);
        CREATE TABLE scientific_records (
          id TEXT, project_id TEXT REFERENCES projects(id),
          variable TEXT, content_sha256 TEXT
        );
        CREATE TABLE environmental_cache_entries (
          id TEXT, project_id TEXT, cache_key TEXT, source_url TEXT
        );
        INSERT INTO scientific_records VALUES (
          'record-1', 'missing-project', 'temperature', 'frozen-digest'
        );
    """
    status, report = _inspect(tmp_path, ddl, "0038")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["table_signatures"]["scientific_records"] is True
    assert report["foreign_key_violations"] == 1
    assert report["foreign_key_violation_sources"] == [
        {"table": "scientific_records", "parent_table": "projects", "count": 1}
    ]
    assert report["automatic_migration_authorized"] is False
    assert any("foreign-key violations" in issue for issue in report["issues"])


def test_refuses_duplicate_review_requests_without_real_0038_unique_constraint(
    tmp_path: Path,
) -> None:
    # A valid event CHECK does not prevent duplicate scientist review actions.
    # The actual 1.6/0038 migration guarantees one event per item/request pair.
    ddl = """
        CREATE TABLE projects (id TEXT PRIMARY KEY);
        CREATE TABLE review_queues (id TEXT PRIMARY KEY, project_id TEXT NOT NULL);
        CREATE TABLE review_queue_items (
          id TEXT PRIMARY KEY, review_queue_id TEXT, project_id TEXT
        );
        CREATE TABLE review_queue_item_events (
          id TEXT PRIMARY KEY, project_id TEXT, review_queue_id TEXT,
          review_queue_item_id TEXT, client_request_id TEXT,
          event_type TEXT, actor TEXT,
          CHECK(event_type IN ('comment', 'assign', 'unassign'))
        );
        INSERT INTO projects VALUES ('project-1');
        INSERT INTO review_queues VALUES ('queue-1', 'project-1');
        INSERT INTO review_queue_items VALUES ('item-1', 'queue-1', 'project-1');
        INSERT INTO review_queue_item_events VALUES
          ('event-1', 'project-1', 'queue-1', 'item-1', 'same-request', 'comment', 'a'),
          ('event-2', 'project-1', 'queue-1', 'item-1', 'same-request', 'comment', 'a');
    """
    status, report = _inspect(tmp_path, ddl, "0038")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["review_event_check"] == "coordination"
    assert report["qc_event_scope_violations"] == 0
    assert report["qc_event_type_violations"] == 0
    assert report["qc_request_key_unique"] is False
    assert report["automatic_migration_authorized"] is False
    assert any("item/request uniqueness" in issue for issue in report["issues"])


def test_refuses_nullable_qc_request_ids_despite_a_real_unique_constraint(
    tmp_path: Path,
) -> None:
    # The applied 1.6/0038 migration makes client_request_id NOT NULL.
    # SQLite UNIQUE allows repeat NULL values, corrupting review idempotency
    # even when a real unique index and valid event CHECK are present.
    ddl = """
        CREATE TABLE projects (id TEXT PRIMARY KEY);
        CREATE TABLE review_queues (id TEXT PRIMARY KEY, project_id TEXT NOT NULL);
        CREATE TABLE review_queue_items (
          id TEXT PRIMARY KEY, review_queue_id TEXT, project_id TEXT
        );
        CREATE TABLE review_queue_item_events (
          id TEXT PRIMARY KEY NOT NULL, project_id TEXT NOT NULL,
          review_queue_id TEXT NOT NULL, review_queue_item_id TEXT NOT NULL,
          client_request_id TEXT, event_type TEXT NOT NULL,
          actor TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(review_queue_item_id, client_request_id),
          CHECK(event_type IN ('comment', 'assign', 'unassign'))
        );
        INSERT INTO projects VALUES ('project-1');
        INSERT INTO review_queues VALUES ('queue-1', 'project-1');
        INSERT INTO review_queue_items VALUES ('item-1', 'queue-1', 'project-1');
        INSERT INTO review_queue_item_events VALUES
          ('event-1', 'project-1', 'queue-1', 'item-1', NULL,
           'comment', 'scientist', '2026-11-22T08:00:00'),
          ('event-2', 'project-1', 'queue-1', 'item-1', NULL,
           'comment', 'scientist', '2026-11-22T08:01:00');
    """
    status, report = _inspect(tmp_path, ddl, "0038")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["review_event_check"] == "coordination"
    assert report["qc_request_key_unique"] is True
    assert report["qc_required_columns_not_null"] is False
    assert report["qc_event_scope_violations"] == 0
    assert report["qc_event_type_violations"] == 0
    assert report["automatic_migration_authorized"] is False
    assert any("missing or nullable" in issue for issue in report["issues"])


def test_refuses_empty_qc_review_schema_without_real_parent_tables(
    tmp_path: Path,
) -> None:
    # An empty event table can satisfy every local event CHECK/UNIQUE/NOT NULL
    # contract while missing the queue, item, and project tables on which the
    # real 1.6 migration depends. No populated event is needed to expose it.
    ddl = """
        CREATE TABLE review_queue_item_events (
          id TEXT PRIMARY KEY NOT NULL, project_id TEXT NOT NULL,
          review_queue_id TEXT NOT NULL, review_queue_item_id TEXT NOT NULL,
          client_request_id TEXT NOT NULL, event_type TEXT NOT NULL,
          actor TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(review_queue_item_id, client_request_id),
          CHECK(event_type IN ('comment', 'assign', 'unassign'))
        );
    """
    status, report = _inspect(tmp_path, ddl, "0038")
    assert status == 2
    assert report["classification"] == "ambiguous"
    assert report["qc_request_key_unique"] is True
    assert report["qc_required_columns_not_null"] is True
    assert report["qc_event_scope_violations"] is None
    assert report["qc_event_type_violations"] == 0
    assert report["automatic_migration_authorized"] is False
    assert any("parent tables missing" in issue for issue in report["issues"])


@pytest.mark.parametrize(
    ("original_check", "current_check", "expected_status"),
    [
        ("triage_complete", "coordination", 2),
        ("triage_complete", "triage", 2),
        ("triage", "coordination", 2),
        ("coordination", "triage_complete", 0),
        ("triage_complete", "triage_complete", 0),
    ],
)
def test_lineage_comparison_preserves_qc_event_vocabulary(
    tmp_path: Path, original_check: str, current_check: str, expected_status: int
) -> None:
    # Isolate the comparator contract: identical retained row and model
    # fingerprints do not excuse narrowing the allowed 0039/0040 event types.
    fingerprint = {"sha256": "a" * 64, "columns": ["id"], "row_count": 1}
    report = {
        "schema_version": "reefvision-sqlite-lineage-forensics-0001",
        "affected_table_content_fingerprint_algorithm": "reefvision-sqlite-row-multiset-v1",
        "sqlite_integrity_check_ok": True,
        "foreign_key_violations": 0,
        "affected_table_row_counts": {"review_queue_item_events": 1},
        "affected_table_content_fingerprints": {"review_queue_item_events": fingerprint},
        "qc_event_scope_violations": 0,
        "qc_event_type_violations": 0,
        "qc_request_key_unique": True,
        "qc_required_columns_not_null": True,
        "qc_event_foreign_keys_valid": True,
        "qc_event_primary_key_valid": True,
        "model_registry_row_count": 1,
        "model_registry_checkpoint_files_verified": True,
        "model_registry_checkpoint_evidence": {"counts": {"verified": 1}},
        "model_registry_metadata_fingerprint": fingerprint,
    }
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps(dict(report, review_event_check=original_check)))
    candidate.write_text(json.dumps(dict(report, review_event_check=current_check)))
    script = Path(__file__).resolve().parents[4] / "scripts" / "compare-lineage-reports.py"
    result = subprocess.run(
        [sys.executable, str(script), str(baseline), str(candidate)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_status, result.stderr
    comparison = json.loads(result.stdout)
    assert comparison["retained_content_matches"] is (expected_status == 0)
    assert comparison["automatic_migration_authorized"] is False
    assert comparison["table_results"]["review_queue_item_events"] == "full_content_matches"
    assert comparison["issues"] == (
        ["QC event CHECK narrows the baseline audit vocabulary"] if expected_status else []
    )
