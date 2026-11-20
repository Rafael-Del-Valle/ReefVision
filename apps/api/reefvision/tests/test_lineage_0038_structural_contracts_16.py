"""Read-only post-0037 SQLite structural evidence for conflicting revision 0038."""

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "inspect-alembic-lineage.py"
SPEC = importlib.util.spec_from_file_location("inspect_0038_structures", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _create_scientific(db: sqlite3.Connection, variant: str) -> None:
    column = "source_kind VARCHAR(30) NOT NULL,"
    if variant == "missing_column":
        column = ""
    if variant == "unexpected_default":
        column = "source_kind VARCHAR(30) NOT NULL DEFAULT 'PRIVATE_FUTURE_SOURCE',"
    if variant == "collated_source":
        column = "source_kind VARCHAR(30) NOT NULL COLLATE NOCASE,"
    foreign_key = "REFERENCES images(id) ON DELETE RESTRICT"
    if variant == "wrong_fk":
        foreign_key = "REFERENCES images(id) ON DELETE SET NULL"
    if variant == "wrong_onupdate_fk":
        foreign_key = "REFERENCES images(id) ON UPDATE CASCADE ON DELETE RESTRICT"
    if variant == "deferred_fk":
        foreign_key += " DEFERRABLE INITIALLY DEFERRED"
    image_column = "image_id VARCHAR(36)"
    if variant == "optional_notnull":
        image_column += " NOT NULL DEFAULT 'PRIVATE_FUTURE_IMAGE'"
    extra = ", generated_tag TEXT GENERATED ALWAYS AS (id) VIRTUAL"
    if variant != "hidden_column":
        extra = ""
    if variant == "unexpected_check":
        extra += ", CHECK (source_kind = 'instrument')"
    if variant == "comment_decoy":
        extra += " /* CHECK (source_kind = 'private_future') DEFERRABLE WITHOUT ROWID */"
    table_options = " WITHOUT ROWID" if variant == "without_rowid" else ""
    db.execute(
        "CREATE TABLE scientific_records ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "variable VARCHAR(100) NOT NULL, "
        f"{column} "
        "observed_at DATETIME NOT NULL, "
        f"{image_column} {foreign_key}, "
        "video_id VARCHAR(36) REFERENCES videos(id) ON DELETE RESTRICT, "
        "track_id VARCHAR(36) REFERENCES video_tracks(id) ON DELETE RESTRICT, "
        "model_run_id VARCHAR(36) REFERENCES jobs(id) ON DELETE RESTRICT, "
        "payload_json JSON NOT NULL, content_sha256 VARCHAR(64) NOT NULL, "
        f"created_at DATETIME NOT NULL{extra}){table_options}"
    )
    if variant != "missing_index":
        columns = {
            "partial_lookup": "(project_id, variable, observed_at) WHERE observed_at IS NOT NULL",
            "nocase_lookup": "(project_id COLLATE NOCASE, variable, observed_at)",
            "desc_lookup": "(project_id, variable, observed_at DESC)",
        }.get(variant, "(project_id, variable, observed_at)")
        db.execute(
            "CREATE INDEX ix_scientific_project_variable_time ON scientific_records " + columns
        )
    columns = (
        "id, project_id, variable, source_kind, observed_at, payload_json, "
        "content_sha256, created_at"
        if variant != "missing_column"
        else "id, project_id, variable, observed_at, payload_json, content_sha256, created_at"
    )
    values = (
        "'s1', 'p1', 'coral growth', 'instrument', '2026-11-16', "
        "'PRIVATE_CORAL_NOTE', 'digest', '2026-11-16'"
        if variant != "missing_column"
        else "'s1', 'p1', 'coral growth', '2026-11-16', "
        "'PRIVATE_CORAL_NOTE', 'digest', '2026-11-16'"
    )
    db.execute(f"INSERT INTO scientific_records ({columns}) VALUES ({values})")
    if variant == "unexpected_trigger":
        # This would rewrite a future observed value, even though the base
        # table's columns, keys and current rows look migration-compatible.
        db.execute(
            "CREATE TRIGGER research_mutation AFTER INSERT ON scientific_records "
            "BEGIN UPDATE scientific_records SET variable = 'PRIVATE_TRIGGER_BODY' "
            "WHERE id = NEW.id; END"
        )


def _create_qc(db: sqlite3.Connection, variant: str) -> None:
    fk = "REFERENCES review_queues(id) ON DELETE CASCADE"
    if variant == "wrong_fk":
        fk = "REFERENCES review_queues(id) ON DELETE RESTRICT"
    if variant == "wrong_onupdate_fk":
        fk = "REFERENCES review_queues(id) ON UPDATE CASCADE ON DELETE CASCADE"
    if variant == "deferred_fk":
        fk += " DEFERRABLE INITIALLY DEFERRED"
    actor = "actor VARCHAR(100) NOT NULL"
    if variant == "nullable_actor":
        actor = "actor VARCHAR(100)"
    if variant == "unexpected_default":
        actor = "actor VARCHAR(100) NOT NULL DEFAULT 'PRIVATE_FUTURE_ACTOR'"
    comment_column = "comment TEXT NOT NULL" if variant == "optional_notnull" else "comment TEXT"
    event_type = "event_type VARCHAR(20) NOT NULL"
    if variant == "collated_event_type":
        event_type += " COLLATE NOCASE"
    if variant == "ignore_conflict":
        event_type += " ON CONFLICT IGNORE"
    values = ["comment", "assign", "unassign"]
    if variant == "old_check_broadened":
        values.append("approve")
    if variant in {"triage_0039", "triage_0040"}:
        values.extend(("triage_start", "triage_skip", "triage_return"))
    if variant == "triage_0040":
        values.append("triage_complete")
    quoted_values = ", ".join(f"'{value}'" for value in values)
    check_name = (
        "unreviewed_event_vocab"
        if variant == "renamed_check"
        else "ck_review_queue_item_event_type"
    )
    check = (
        f", CONSTRAINT {check_name} CHECK (event_type IN ({quoted_values}))"
        if variant != "missing_check"
        else ""
    )
    if variant == "extra_check":
        check += ", CHECK (comment IS NOT NULL)"
    if variant == "comment_decoy":
        check += " /* CHECK (event_type IN ('approve')) DEFERRABLE WITHOUT ROWID */"
    unique = ", UNIQUE (review_queue_item_id, client_request_id)"
    if variant == "missing_unique":
        unique = ""
    table_options = " WITHOUT ROWID" if variant == "without_rowid" else ""
    db.execute(
        "CREATE TABLE review_queue_item_events ("
        "id VARCHAR(36) NOT NULL PRIMARY KEY, "
        f"review_queue_id VARCHAR(36) NOT NULL {fk}, "
        "review_queue_item_id VARCHAR(36) NOT NULL "
        "REFERENCES review_queue_items(id) ON DELETE CASCADE, "
        "project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        f"client_request_id VARCHAR(36) NOT NULL, {event_type}, "
        f"{actor}, {comment_column}, assignee VARCHAR(100), "
        f"created_at DATETIME NOT NULL{unique}{check}){table_options}"
    )
    if variant != "missing_index":
        columns = {
            "partial_lookup": "(review_queue_item_id, created_at) WHERE created_at IS NOT NULL",
            "nocase_lookup": "(review_queue_item_id COLLATE NOCASE, created_at)",
            "desc_lookup": "(review_queue_item_id, created_at DESC)",
        }.get(variant, "(review_queue_item_id, created_at)")
        db.execute(
            "CREATE INDEX ix_review_queue_item_events_item_created "
            "ON review_queue_item_events " + columns
        )
    db.execute(
        "CREATE INDEX ix_review_queue_item_events_queue_created "
        "ON review_queue_item_events (review_queue_id, created_at)"
    )
    db.execute(
        "INSERT INTO review_queue_item_events "
        "(id, review_queue_id, review_queue_item_id, project_id, "
        "client_request_id, event_type, actor, comment, created_at) "
        "VALUES ('event1', 'queue1', 'item1', 'p1', "
        "'request1', 'comment', 'local scientist', 'PRIVATE_CORAL_NOTE', '2026-11-16')"
    )
    if variant == "unexpected_trigger":
        # A future review insertion would be silently rewritten.
        db.execute(
            "CREATE TRIGGER review_mutation AFTER INSERT ON review_queue_item_events "
            "BEGIN UPDATE review_queue_item_events "
            "SET comment = 'PRIVATE_TRIGGER_BODY' WHERE id = NEW.id; END"
        )


@pytest.mark.parametrize(
    ("family", "variant"),
    [
        ("scientific", "valid"),
        ("scientific", "unexpected_default"),
        ("scientific", "unexpected_check"),
        ("scientific", "collated_source"),
        ("scientific", "comment_decoy"),
        ("scientific", "optional_notnull"),
        ("scientific", "missing_column"),
        ("scientific", "wrong_fk"),
        ("scientific", "wrong_onupdate_fk"),
        ("scientific", "deferred_fk"),
        ("scientific", "without_rowid"),
        ("scientific", "partial_lookup"),
        ("scientific", "nocase_lookup"),
        ("scientific", "desc_lookup"),
        ("scientific", "missing_index"),
        ("scientific", "hidden_column"),
        ("scientific", "unexpected_trigger"),
        ("qc", "valid"),
        ("qc", "unexpected_default"),
        ("qc", "missing_check"),
        ("qc", "old_check_broadened"),
        ("qc", "extra_check"),
        ("qc", "renamed_check"),
        ("qc", "collated_event_type"),
        ("qc", "ignore_conflict"),
        ("qc", "comment_decoy"),
        ("qc", "triage_0039"),
        ("qc", "triage_0040"),
        ("qc", "optional_notnull"),
        ("qc", "wrong_fk"),
        ("qc", "wrong_onupdate_fk"),
        ("qc", "deferred_fk"),
        ("qc", "without_rowid"),
        ("qc", "partial_lookup"),
        ("qc", "nocase_lookup"),
        ("qc", "missing_check"),
        ("qc", "old_check_broadened"),
        ("qc", "extra_check"),
        ("qc", "collated_event_type"),
        ("qc", "ignore_conflict"),
        ("scientific", "unexpected_check"),
        ("qc", "desc_lookup"),
        ("qc", "nullable_actor"),
        ("qc", "missing_unique"),
        ("qc", "missing_index"),
        ("qc", "unexpected_trigger"),
    ],
)
def test_read_only_structural_contract_catches_colliding_0038_shape(
    tmp_path: Path, family: str, variant: str
) -> None:
    path = tmp_path / "reconciled-copy-only.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);"
            "INSERT INTO alembic_version VALUES ('0038');"
            "CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY);"
            "CREATE TABLE review_queues (id VARCHAR(36) PRIMARY KEY);"
            "CREATE TABLE review_queue_items (id VARCHAR(36) PRIMARY KEY);"
            "INSERT INTO projects VALUES ('p1');"
            "INSERT INTO review_queues VALUES ('queue1');"
            "INSERT INTO review_queue_items VALUES ('item1');"
        )
        if family == "scientific":
            _create_scientific(db, variant)
        else:
            _create_qc(db, variant)
        db.commit()

    before = path.read_bytes()
    report = module.inspect(path, verify_structural_contracts=True)
    target = "scientific_records" if family == "scientific" else "review_queue_item_events"
    other = "review_queue_item_events" if family == "scientific" else "scientific_records"
    mismatch_warning = f"lineage_table_contract_mismatch_{target}"
    equivalent = variant in {"valid", "comment_decoy", "triage_0039", "triage_0040"}
    assert report["structural_contracts"][target] == ("matches" if equivalent else "mismatch")
    assert report["structural_contracts"][other] == "absent"
    assert (mismatch_warning in report["warnings"]) is (not equivalent)
    assert report["upgrade_authorized"] is False
    assert "revision_0038_requires_schema_lineage_reconciliation" in report["warnings"]
    assert "PRIVATE_CORAL_NOTE" not in json.dumps(report)
    assert path.read_bytes() == before
    assert module.inspect(path)["structural_contracts"] == {}
    assert path.read_bytes() == before


def test_strict_structural_audit_rejects_forged_scientific_0038(
    tmp_path: Path,
) -> None:
    path = tmp_path / "structural-evidence.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version VALUES ('0038')")
        db.execute("CREATE TABLE scientific_records (id TEXT PRIMARY KEY, private_note TEXT)")
        db.execute("INSERT INTO scientific_records VALUES ('s1', 'PRIVATE_CORAL_NOTE')")
        db.commit()
    before = path.read_bytes()
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(path),
            "--verify-structural-contracts",
            "--fail-on-warning",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report["structural_contracts"]["scientific_records"] == "mismatch"
    assert "lineage_table_contract_mismatch_scientific_records" in report["warnings"]
    assert "PRIVATE_CORAL_NOTE" not in completed.stdout
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("family", "variant"),
    [
        ("scientific", "unexpected_trigger"),
        ("qc", "unexpected_trigger"),
        ("scientific", "wrong_onupdate_fk"),
        ("scientific", "deferred_fk"),
        ("scientific", "without_rowid"),
        ("qc", "deferred_fk"),
        ("qc", "without_rowid"),
        ("scientific", "unexpected_default"),
        ("qc", "optional_notnull"),
        ("scientific", "partial_lookup"),
        ("qc", "nocase_lookup"),
    ],
)
def test_strict_0038_semantic_drift_is_redacted_and_read_only(
    tmp_path: Path, family: str, variant: str
) -> None:
    path = tmp_path / "triggered-lineage-copy.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);"
            "INSERT INTO alembic_version VALUES ('0038');"
            "CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY);"
            "CREATE TABLE review_queues (id VARCHAR(36) PRIMARY KEY);"
            "CREATE TABLE review_queue_items (id VARCHAR(36) PRIMARY KEY);"
            "INSERT INTO projects VALUES ('p1');"
            "INSERT INTO review_queues VALUES ('queue1');"
            "INSERT INTO review_queue_items VALUES ('item1');"
        )
        if family == "scientific":
            _create_scientific(db, variant)
        else:
            _create_qc(db, variant)
        db.commit()

    before = path.read_bytes()
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(path),
            "--verify-structural-contracts",
            "--fail-on-warning",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    target = "scientific_records" if family == "scientific" else "review_queue_item_events"
    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report["structural_contracts"][target] == "mismatch"
    assert f"lineage_table_contract_mismatch_{target}" in report["warnings"]
    assert report["upgrade_authorized"] is False
    assert "PRIVATE_CORAL_NOTE" not in completed.stdout
    assert "PRIVATE_TRIGGER_BODY" not in completed.stdout
    assert path.read_bytes() == before
